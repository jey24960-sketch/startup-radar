"""The fixed baseline continuation cannot become a generic recovery bypass."""
import os
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
import requests
import psycopg
from psycopg.types.json import Jsonb

from test_database import db  # noqa: F401
from tools import continue_discovery_baseline as recovery


DB = pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Explicit test database required')


def public_run(**changes):
    return {'id':int(recovery.PRIOR_RUN_ID),'head_sha':recovery.PRIOR_HEAD,
            'head_branch':recovery.PRIOR_BRANCH,'status':'completed',**changes}


def response(payload=None, status=200):
    return SimpleNamespace(status_code=status,json=lambda:payload)


def verified():
    return {'run_id':recovery.PRIOR_RUN_ID,'head_sha':recovery.PRIOR_HEAD,
            'branch':recovery.PRIOR_BRANCH,'status':'completed'}


def api_result(adapter, *, status='SUCCESS', complete=True):
    return {'source_slug':adapter.lower(),'adapter':adapter,'status':status,
            'discovered':2,'parsed':2,'fetched':2,'failures':[],
            'coverage':{'scope_completed':complete,'pagination_complete':complete}}


def test_public_run_lookup_is_fixed_unauthenticated_bounded_and_does_not_follow_redirects():
    calls=[]
    def fetch(url,**kwargs):
        calls.append((url,kwargs))
        return response(public_run())
    assert recovery.verify_prior_run(fetcher=fetch)==verified()
    assert calls==[(recovery.RUN_URL,{'timeout':20,'allow_redirects':False,
                                   'headers':{'Accept':'application/vnd.github+json'}})]


@pytest.mark.parametrize('change',[
    {'id':1},{'head_sha':'different'},{'head_branch':'another-branch'},{'status':'unknown'},
])
def test_mismatched_run_or_unrecognized_status_cannot_confirm_termination(change):
    with pytest.raises(recovery.ContinuationRefused):
        recovery.verify_prior_run(fetcher=lambda *_args,**_kw:response(public_run(**change)))


@pytest.mark.parametrize('http_status',[301,401,403,429,500])
def test_http_failure_never_confirms_termination_or_exposes_a_response(http_status):
    with pytest.raises(recovery.ContinuationRefused,match='PUBLIC_RUN_LOOKUP_REJECTED') as error:
        recovery.verify_prior_run(fetcher=lambda *_args,**_kw:response({'secret':'DO_NOT_PRINT'},http_status))
    assert 'DO_NOT_PRINT' not in str(error.value)


def test_network_exception_does_not_expose_url_or_credentials():
    def broken(*_args,**_kwargs):
        raise requests.ConnectionError('https://secret.invalid/?token=DO_NOT_PRINT')
    with pytest.raises(recovery.ContinuationRefused) as error:
        recovery.verify_prior_run(fetcher=broken)
    assert str(error.value)=='PUBLIC_RUN_LOOKUP_FAILED'


def test_termination_poll_is_bounded_and_requires_completed_status():
    elapsed=[0]
    calls=[]
    def sleep(seconds): elapsed[0]+=seconds
    def fetch(*_args,**kwargs):
        calls.append(kwargs['timeout'])
        return response(public_run(status='in_progress'))
    with pytest.raises(recovery.ContinuationRefused,match='TERMINATION_UNCONFIRMED'):
        recovery.verify_prior_run(fetcher=fetch,clock=lambda:elapsed[0],sleep=sleep,wait_seconds=25)
    assert elapsed[0]==25 and calls==[20,15,5]


def test_running_then_completed_run_is_only_accepted_after_completion():
    elapsed=[0]
    payloads=iter([public_run(status='in_progress'),public_run()])
    assert recovery.verify_prior_run(fetcher=lambda *_args,**_kw:response(next(payloads)),
        clock=lambda:elapsed[0],sleep=lambda seconds:elapsed.__setitem__(0,elapsed[0]+seconds))==verified()
    assert elapsed[0]==10


def test_both_complete_successful_official_scopes_are_required():
    sources=[api_result('KSTARTUP'),api_result('BIZINFO')]
    assert recovery.official_baseline_verified(sources)
    assert recovery.official_baseline_verified(sources+[{'adapter':'HTML','status':'FAILED'}])
    assert not recovery.official_baseline_verified(sources[:1])
    assert not recovery.official_baseline_verified([api_result('KSTARTUP',complete=False),sources[1]])
    assert not recovery.official_baseline_verified([api_result('KSTARTUP',status='PARTIAL'),sources[1]])
    assert not recovery.official_baseline_verified(sources+[api_result('BIZINFO',status='FAILED')])


@pytest.fixture
def baseline_db(db):
    db.upsert_source('kstartup','K-Startup','KSTARTUP',{})
    db.upsert_source('bizinfo','BizInfo','BIZINFO',{})
    with db.transaction() as c:
        settings=c.execute("select key,value from startup_radar.runtime_settings where key in ('daily_discovery','early_announcements')").fetchall()
        c.execute("update startup_radar.runtime_settings set value=jsonb_set(value,'{enabled}','true') where key='daily_discovery'")
        c.execute("update startup_radar.runtime_settings set value=value||'{\"enabled\":false,\"active_from\":null}'::jsonb where key='early_announcements'")
        c.execute("insert into startup_radar.worker_executions(id,kind,state,owner) values(%s,'DISCOVER','RUNNING',%s)",
                  (recovery.PRIOR_EXECUTION_ID,Jsonb({'github_run_id':recovery.PRIOR_RUN_ID,'fixture':True})))
        c.execute("insert into startup_radar.ingestion_runs(id,status,trigger_type,summary) values(%s,'RUNNING','daily-discovery-retry',%s)",
                  (recovery.PRIOR_INGESTION_ID,Jsonb({'preserved_fixture':'source evidence is retained'})))
        c.execute('insert into startup_radar.discovery_slots(slot_start,execution_id) values(%s,%s)',
                  (recovery.SLOT,recovery.PRIOR_EXECUTION_ID))
        # A prior ordinary retry must remain visible and must not be reset by
        # this separately authorized, fixed continuation.
        c.execute("insert into startup_radar.admin_audit(action,entity_id,detail) values('DISCOVERY_SLOT_RETRY',%s,%s)",
                  (recovery.SLOT.isoformat(),Jsonb({'prior_retry':'preserved'})))
    try: yield db
    finally:
        with db.transaction() as c:
            for setting in settings:
                c.execute('update startup_radar.runtime_settings set value=%s where key=%s',
                          (Jsonb(setting['value']),setting['key']))


def collector(status='PARTIAL_SUCCESS', *, official_complete=True, calls=None):
    def collect(db,sources,**kwargs):
        if calls is not None: calls.append(kwargs)
        assert {source['adapter'] for source in sources}=={'KSTARTUP','BIZINFO'}
        assert kwargs=={'structured_only':True,'trigger':'daily-discovery-baseline-continuation'}
        outcomes=[api_result('KSTARTUP',complete=official_complete),api_result('BIZINFO')]
        if status=='PARTIAL_SUCCESS':
            outcomes.append({'adapter':'HTML','status':'FAILED','failures':[{'kind':'TLS_ERROR'}]})
        with db.transaction() as c:
            ingestion=c.execute('insert into startup_radar.ingestion_runs(status,trigger_type,finished_at) '
                                'values(%s,%s,now()) returning id',(status,kwargs['trigger'])).fetchone()['id']
            # This baseline first discovery precedes activation by construction.
            baseline_time=c.execute('select now() at').fetchone()['at']
        return {'id':str(ingestion),'status':status,'sources':outcomes,'baseline_time':baseline_time.isoformat()}
    return collect


@DB
def test_continuation_preserves_preimages_retry_guard_and_never_publishes(baseline_db,monkeypatch):
    with baseline_db.transaction() as c:
        before_worker=c.execute('select to_jsonb(w) value from startup_radar.worker_executions w where id=%s',
                                (recovery.PRIOR_EXECUTION_ID,)).fetchone()['value']
        before_slot=c.execute('select to_jsonb(s) value from startup_radar.discovery_slots s').fetchone()['value']
        before_ingestion=c.execute('select to_jsonb(r) value from startup_radar.ingestion_runs r where id=%s',
                                   (recovery.PRIOR_INGESTION_ID,)).fetchone()['value']
    monkeypatch.setattr('radar.early_announcements.plan_early_notices',lambda *_args,**_kw:pytest.fail('Continuation planned publication'))
    monkeypatch.setattr('radar.early_announcements.announce_early',lambda *_args,**_kw:pytest.fail('Continuation sent notification'))
    calls=[]
    result=recovery.continue_baseline(baseline_db,verifier=verified,collector=collector(calls=calls))
    assert result['status']=='PARTIAL_SUCCESS' and result['core_baseline_verified']
    assert result['early_announcements_activated']
    assert len(calls)==1
    with baseline_db.transaction() as c:
        audit=c.execute('select detail from startup_radar.admin_audit where action=%s',(recovery.ACTION,)).fetchone()['detail']
        assert audit['previous_worker']==before_worker
        assert audit['previous_slot']==before_slot
        assert audit['previous_ingestion']==before_ingestion
        old=c.execute('select * from startup_radar.ingestion_runs where id=%s',(recovery.PRIOR_INGESTION_ID,)).fetchone()
        assert old['status']=='FAILED' and old['summary']['partial_effects']
        assert old['summary']['preserved_fixture']=='source evidence is retained'
        slot=c.execute('select * from startup_radar.discovery_slots').fetchone()
        assert str(slot['execution_id'])==result['execution_id'] and slot['finished_at']
        worker=c.execute('select * from startup_radar.worker_executions where id=%s',(result['execution_id'],)).fetchone()
        assert worker['state']=='PARTIAL_SUCCESS' and worker['finished_at']
        original=c.execute('select state from startup_radar.worker_executions where id=%s',(recovery.PRIOR_EXECUTION_ID,)).fetchone()
        assert original['state']=='ABANDONED'
        assert c.execute("select detail from startup_radar.admin_audit where action='DISCOVERY_SLOT_RETRY'").fetchone()['detail']=={'prior_retry':'preserved'}
        setting=c.execute("select value from startup_radar.runtime_settings where key='early_announcements'").fetchone()['value']
        new_ingestion=c.execute('select finished_at from startup_radar.ingestion_runs where id=%s',(result['ingestion_run_id'],)).fetchone()
        assert setting['enabled'] and datetime.fromisoformat(setting['active_from'])>=new_ingestion['finished_at']
        assert c.execute('select count(*) n from startup_radar.weekly_briefings').fetchone()['n']==0
        assert c.execute('select count(*) n from startup_radar.early_notices').fetchone()['n']==0


@DB
def test_incomplete_official_scope_never_activates_early_announcements(baseline_db):
    result=recovery.continue_baseline(baseline_db,verifier=verified,
                                      collector=collector(official_complete=False))
    assert result['status']=='PARTIAL_SUCCESS' and not result['core_baseline_verified']
    assert not result['early_announcements_activated']
    with baseline_db.transaction() as c:
        assert not c.execute("select value from startup_radar.runtime_settings where key='early_announcements'").fetchone()['value']['enabled']


@DB
def test_duplicate_continuation_is_refused_before_any_recovery(baseline_db,monkeypatch):
    with baseline_db.transaction() as c:
        c.execute('insert into startup_radar.admin_audit(action,entity_id,detail) values(%s,%s,%s)',
                  (recovery.ACTION,recovery.PRIOR_EXECUTION_ID,Jsonb({'existing':'preserve'})))
    monkeypatch.setattr(recovery,'recover_execution',lambda *_args,**_kw:pytest.fail('Duplicate recovered an owner'))
    with pytest.raises(recovery.ContinuationRefused,match='ALREADY_RESERVED'):
        recovery.continue_baseline(baseline_db,verifier=verified)


@DB
def test_unverified_public_termination_cannot_change_database_state(baseline_db):
    def unavailable(): raise recovery.ContinuationRefused('PRIOR_RUN_TERMINATION_UNCONFIRMED')
    with pytest.raises(recovery.ContinuationRefused):
        recovery.continue_baseline(baseline_db,verifier=unavailable)
    with baseline_db.transaction() as c:
        assert c.execute('select state from startup_radar.worker_executions where id=%s',(recovery.PRIOR_EXECUTION_ID,)).fetchone()['state']=='RUNNING'
        assert not c.execute('select 1 from startup_radar.admin_audit where action=%s',(recovery.ACTION,)).fetchone()


@pytest.mark.parametrize('mismatch',['owner','slot'])
@DB
def test_wrong_database_owner_or_slot_cannot_be_recovered(baseline_db,mismatch):
    with baseline_db.transaction() as c:
        if mismatch=='owner':
            c.execute("update startup_radar.worker_executions set owner=jsonb_set(owner,'{github_run_id}','\"different\"') where id=%s",
                      (recovery.PRIOR_EXECUTION_ID,))
        else:
            other=uuid4()
            c.execute("insert into startup_radar.worker_executions(id,kind,state,owner,finished_at) values(%s,'DISCOVER','FAILED','{}',now())",(other,))
            c.execute('update startup_radar.discovery_slots set execution_id=%s',(other,))
    with pytest.raises(recovery.ContinuationRefused):
        recovery.continue_baseline(baseline_db,verifier=verified)
    with baseline_db.transaction() as c:
        assert c.execute('select state from startup_radar.worker_executions where id=%s',(recovery.PRIOR_EXECUTION_ID,)).fetchone()['state']=='RUNNING'


@DB
def test_uncaught_collection_error_retains_durable_running_owner(baseline_db):
    def uncertain(*_args,**_kwargs): raise RuntimeError('https://secret.invalid/?token=DO_NOT_PRINT')
    result=recovery.continue_baseline(baseline_db,verifier=verified,collector=uncertain)
    assert result['status']=='UNCERTAIN' and result['reason']=='RuntimeError'
    assert 'DO_NOT_PRINT' not in str(result)
    with baseline_db.transaction() as c:
        worker=c.execute('select state,finished_at from startup_radar.worker_executions where id=%s',
                         (result['execution_id'],)).fetchone()
        assert worker['state']=='RUNNING' and worker['finished_at'] is None
        assert c.execute('select result from startup_radar.discovery_slots').fetchone()['result']['status']=='UNCERTAIN'


@DB
def test_uncertain_owner_finalization_does_not_automatically_release_it(baseline_db,monkeypatch):
    def lost_acknowledgement(*_args,**_kwargs): raise RuntimeError('Unconfirmed finalization')
    monkeypatch.setattr(recovery,'finish_execution',lost_acknowledgement)
    result=recovery.continue_baseline(baseline_db,verifier=verified,collector=collector())
    assert result['status']=='UNCERTAIN'
    assert result['reason']=='CONTINUATION_OWNER_FINALIZATION_UNCERTAIN'
    with baseline_db.transaction() as c:
        worker=c.execute('select state,finished_at from startup_radar.worker_executions where id=%s',
                         (result['execution_id'],)).fetchone()
        assert worker['state']=='RUNNING' and worker['finished_at'] is None


@DB
@pytest.mark.skipif(not psycopg.Pipeline.is_supported(),reason='libpq pipeline support required')
def test_continuation_uses_compatible_session_pipeline_without_changing_owner_contract(baseline_db):
    client=recovery.Database(baseline_db.url,pipeline=True)
    result=recovery.continue_baseline(client,verifier=verified,collector=collector())
    assert result['core_baseline_verified'] and result['early_announcements_activated']
    assert result['status']=='PARTIAL_SUCCESS'
    with baseline_db.transaction() as c:
        assert c.execute('select state from startup_radar.worker_executions where id=%s',
                         (result['execution_id'],)).fetchone()['state']=='PARTIAL_SUCCESS'


def test_cli_zero_exit_requires_official_baseline_and_activation_without_rewriting_partial_status(monkeypatch,capsys):
    monkeypatch.setattr(recovery,'Database',lambda **_kw:object())
    import radar.discovery_connection
    monkeypatch.setattr('radar.discovery_connection.discovery_database_options',lambda:{})
    monkeypatch.setattr(recovery,'continue_baseline',lambda *_args,**_kw:{
        'status':'PARTIAL_SUCCESS','core_baseline_verified':True,'early_announcements_activated':True,
        'sources':[{'adapter':'HTML','status':'FAILED','failures':[{'kind':'TLS_ERROR','url':'https://secret.invalid/?token=DO_NOT_PRINT'}]}],
    })
    assert recovery.main([])==0
    printed=capsys.readouterr().out
    assert 'PARTIAL_SUCCESS' in printed and 'core_baseline_verified' in printed
    assert 'DO_NOT_PRINT' not in printed and 'secret.invalid' not in printed


def test_help_never_opens_database_or_recovers_any_owner(monkeypatch):
    monkeypatch.setattr(recovery,'Database',lambda **_kw:pytest.fail('Help accessed runtime state'))
    with pytest.raises(SystemExit) as error:
        recovery.main(['--help'])
    assert error.value.code==0
