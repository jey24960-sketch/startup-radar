from datetime import datetime,timedelta
import pytest
from psycopg.types.json import Jsonb
from core.clock import SEOUL
from radar.scheduler import tick,run_job
from radar.schedule_attempts import request_ingest_retry,retryable_ingestion
from radar.executions import active_execution,recover_execution
from test_database import db

AT=datetime(2026,9,14,6,17,tzinfo=SEOUL)


def failure(reason='READ_TIMEOUT',retryable=True):
    return {'status':'FAILED','sources':[{'status':'FAILED','failures':[
        {'kind':'TIMEOUT','reason_code':reason,'retryable':retryable}]}]}


def attempts(db):
    with db.transaction() as c:
        return c.execute('select * from startup_radar.schedule_task_attempts order by task_key,attempt_number').fetchall()


def test_successful_daily_claim_is_observed_without_duplicate_execution(db):
    calls=[]
    def execute(*a,**k):calls.append(k);return {'status':'SUCCESS'}
    first=tick(db,at=AT,executor=execute)
    second=tick(db,at=AT+timedelta(minutes=30),executor=execute)
    assert first['status']==second['status']=='SUCCESS' and len(calls)==1
    assert second['tasks']==[] and second['already_successful']==1
    assert second['unresolved_failure']==0 and len(attempts(db))==1


def test_failed_empty_tick_stays_degraded_then_retries_with_separate_history(db):
    calls=[];transport=object()
    def execute(*a,**k):
        calls.append(k['transport'])
        return failure() if len(calls)==1 else {'status':'SUCCESS'}
    first=tick(db,at=AT,transport=transport,executor=execute)
    waiting=tick(db,at=AT+timedelta(minutes=1),transport=transport,executor=execute)
    recovered=tick(db,at=AT+timedelta(minutes=15),transport=transport,executor=execute)
    assert first['status']=='FAILED' and first['retry_scheduled']==1
    assert waiting['tasks']==[] and waiting['status']=='FAILED' and waiting['unresolved_failure']==1
    assert recovered['status']=='SUCCESS' and calls==[transport,None]
    rows=attempts(db)
    assert [r['state'] for r in rows]==['FAILED_RETRYABLE','SUCCESS']
    assert rows[0]['result']==failure() and rows[1]['previous_attempt_id']==rows[0]['id']
    assert rows[1]['origin']=='AUTO_RETRY'


@pytest.mark.parametrize('reason',['ROBOTS_DISALLOWED','HTTP_4XX','CONFIGURATION','AI_SCHEMA','DOCUMENT_PARSE'])
def test_terminal_failures_never_auto_retry(db,reason):
    calls=[]
    def execute(*a,**k):calls.append(1);return failure(reason,False)
    tick(db,at=AT,executor=execute)
    later=tick(db,at=AT+timedelta(hours=3),executor=execute)
    assert len(calls)==1 and later['tasks']==[]
    assert later['status']=='FAILED' and later['terminal_failure']==1 and later['retry_scheduled']==0


def test_retry_budget_exhausts_without_erasing_failures(db):
    calls=[]
    def execute(*a,**k):calls.append(1);return failure('DNS_ERROR')
    for minutes in (0,15,75,180):result=tick(db,at=AT+timedelta(minutes=minutes),executor=execute)
    assert len(calls)==3 and result['terminal_failure']==1
    rows=attempts(db)
    assert len(rows)==3 and rows[-1]['reason_code']=='RETRY_EXHAUSTED'
    assert all(r['result']==failure('DNS_ERROR') for r in rows)


def test_expired_retry_is_closed_and_not_left_in_queue(db):
    tick(db,at=AT,executor=lambda *a,**k:failure())
    with db.transaction() as c:
        c.execute("update startup_radar.runtime_settings set value=value || %s where key='scheduling'",(Jsonb({'ingestion_hour':23}),))
    result=tick(db,at=AT+timedelta(hours=25),executor=lambda *a,**k:pytest.fail('expired retry executed'))
    assert result['terminal_failure']==1 and result['retry_scheduled']==0
    assert attempts(db)[0]['reason_code']=='RETRY_WINDOW_EXPIRED'
    assert attempts(db)[0]['result']==failure()
    with db.transaction() as c:c.execute("update startup_radar.runtime_settings set value=value || '{\"ingestion_hour\":6}' where key='scheduling'")


def test_legacy_failure_is_preserved_and_never_assumed_retryable(db):
    key='INGEST:'+AT.date().isoformat()
    with db.transaction() as c:
        c.execute("insert into startup_radar.schedule_claims(task_key,kind,state,result) values(%s,'INGEST','FAILED',%s)",(key,Jsonb({'error':'legacy robots error'})))
    result=tick(db,at=AT,executor=lambda *a,**k:pytest.fail('legacy cause guessed'))
    assert result['status']=='FAILED' and result['terminal_failure']==1
    row=attempts(db)[0]
    assert row['origin']=='LEGACY_SNAPSHOT' and row['result']=={'error':'legacy robots error'}


def test_dead_owner_requires_verified_recovery_then_explicit_no_delivery_retry(db,monkeypatch):
    monkeypatch.setattr('radar.scheduler.now',lambda:AT)
    def crash(*a,**k):raise SystemExit(7)
    with pytest.raises(SystemExit):run_job(db,'TICK',executor=crash,transport=object())
    owner=active_execution(db);old=attempts(db)[0]
    assert old['execution_id']==owner['id'] and old['state']=='RUNNING'
    with pytest.raises(ValueError,match='stopped'):recover_execution(db,owner['id'],'Not yet verified',False)
    with pytest.raises(ValueError,match='active execution'):request_ingest_retry(db,old['task_key'],'Caller verified test exit')
    recover_execution(db,owner['id'],'SystemExit returned to test; owner cannot resume',True)
    assert attempts(db)[0]['state']=='UNCERTAIN'
    degraded=tick(db,at=AT,executor=lambda *a,**k:pytest.fail('uncertainty auto retried'))
    assert degraded['status']=='UNCERTAIN'
    request_ingest_retry(db,old['task_key'],'Verified terminated owner; acquisition only')
    calls=[]
    def recover(*a,**k):calls.append(k['transport']);return {'status':'SUCCESS'}
    assert run_job(db,'TICK',executor=recover,transport=object())['status']=='SUCCESS'
    assert calls==[None]
    rows=attempts(db)
    assert rows[0]['state']=='UNCERTAIN' and rows[1]['state']=='SUCCESS'
    assert rows[1]['previous_attempt_id']==old['id'] and rows[1]['origin']=='OPERATOR_RETRY'


def test_uncertain_delivery_and_unclassified_errors_do_not_inherit_ingest_retry():
    assert not retryable_ingestion({'status':'UNCERTAIN','sources':failure()['sources']})
    assert not retryable_ingestion({**failure(),'alerts':{'status':'UNCERTAIN'}})
    assert not retryable_ingestion(failure('ROBOTS_HTTP_ERROR'))
    assert not retryable_ingestion({'status':'FAILED','sources':[{'status':'FAILED','failures':[]}]})


@pytest.mark.parametrize('role',['anon','authenticated'])
def test_attempt_ledger_not_exposed_to_client_roles(db,role):
    import psycopg
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with db.transaction() as c:
            c.execute('set local role '+role)
            c.execute('select * from startup_radar.schedule_task_attempts')
