from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from radar.discovery import discovery_slot, discovery_sources
import os
from test_database import db
from psycopg.types.json import Jsonb

SEOUL=ZoneInfo('Asia/Seoul')

@pytest.mark.parametrize('hour,day,slot_hour',[(0,25,18),(5,25,18),(6,26,6),(17,26,6),(18,26,18),(23,26,18)])
def test_twice_daily_slots_are_stable(hour,day,slot_hour):
    slot=discovery_slot(datetime(2026,10,26,hour,31,tzinfo=SEOUL))
    assert (slot.day,slot.hour,slot.minute)==(day,slot_hour,0)

def test_discovery_is_independent_of_the_weekly_one_page_cap():
    sources=[{'slug':'kstartup','adapter':'KSTARTUP','enabled':True,'config':{'max_pages':1,'page_size':20,'weekly_policy':'GFC_WEEKLY_V1'}},
             {'slug':'bizinfo','adapter':'BIZINFO','enabled':True,'config':{'max_pages':1}},
             {'slug':'direct','adapter':'HTML','enabled':True,'config':{'weekly_direct':True,'policy_status':'APPROVED'}},
             {'slug':'deferred','adapter':'HTML','enabled':True,'config':{'weekly_direct':True,'policy_status':'DEFERRED'}},
             {'slug':'disabled','adapter':'KSTARTUP','enabled':False,'config':{}}]
    picked=discovery_sources(sources)
    assert [s['slug'] for s in picked]==['kstartup','bizinfo','direct']
    assert picked[0]['config']['max_pages']==10 and picked[0]['config']['page_size']==100
    assert picked[0]['config']['recent_announcement_pages']==2
    assert picked[1]['config']['max_pages']==20
    assert 'weekly_policy' not in picked[0]['config']
    assert sources[0]['config']['max_pages']==1

@pytest.mark.parametrize('value',[True,0,-1,31,'20'])
def test_invalid_caps_cannot_make_an_unbounded_scan(value):
    with pytest.raises(ValueError):
        discovery_sources([{'adapter':'BIZINFO','config':{}}],{'bizinfo_max_pages':value})


@pytest.fixture
def enabled_discovery(db):
    db.upsert_source('discovery-k','KStartup','KSTARTUP',{})
    db.upsert_source('discovery-b','BizInfo','BIZINFO',{})
    with db.transaction() as c:
        c.execute("update startup_radar.runtime_settings set value=jsonb_set(value,'{enabled}','true') where key='daily_discovery'")
    try: yield db
    finally:
        with db.transaction() as c:
            c.execute("update startup_radar.runtime_settings set value=jsonb_set(value,'{enabled}','false') where key='daily_discovery'")


@pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Explicit test database required')
def test_discovery_is_internal_and_duplicate_slot_never_collects_twice(enabled_discovery):
    from radar.discovery import run_discovery
    calls=[]
    def collect(db,sources,**kwargs):
        calls.append(kwargs)
        assert kwargs=={'trigger':'daily-discovery','structured_only':True}
        assert {s['adapter'] for s in sources}=={'KSTARTUP','BIZINFO'}
        with db.transaction() as c:
            run=c.execute("insert into startup_radar.ingestion_runs(status,trigger_type,finished_at) values('SUCCESS','discovery-test',now()) returning id").fetchone()['id']
        return {'status':'SUCCESS','id':str(run),'sources':[]}
    first=run_discovery(enabled_discovery,collector=collect)
    second=run_discovery(enabled_discovery,collector=collect)
    assert first['state']=='DISCOVERY_COMPLETED'
    assert second['state']=='DUPLICATE_DISCOVERY_SLOT' and not second['executed']
    assert len(calls)==1
    with enabled_discovery.transaction() as c:
        assert c.execute('select count(*) n from startup_radar.discovery_slots').fetchone()['n']==1
        assert c.execute('select count(*) n from startup_radar.weekly_briefings').fetchone()['n']==0
        assert c.execute('select count(*) n from startup_radar.early_notices').fetchone()['n']==0


@pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Explicit test database required')
def test_paused_discovery_never_collects_or_claims_slot(enabled_discovery):
    from radar.discovery import run_discovery
    with enabled_discovery.transaction() as c:
        c.execute("update startup_radar.runtime_settings set value=jsonb_set(value,'{enabled}','false') where key='radar_operation'")
    try:
        result=run_discovery(enabled_discovery,collector=lambda *_args,**_kw:pytest.fail('Paused discovery ran'))
        assert result['status']=='PAUSED'
        with enabled_discovery.transaction() as c:
            assert c.execute('select count(*) n from startup_radar.discovery_slots').fetchone()['n']==0
    finally:
        with enabled_discovery.transaction() as c:
            c.execute("update startup_radar.runtime_settings set value=jsonb_set(value,'{enabled}','true') where key='radar_operation'")


@pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Explicit test database required')
def test_all_source_failure_cannot_plan_an_early_notice(enabled_discovery,monkeypatch):
    from radar.discovery import run_discovery
    monkeypatch.setattr('radar.early_announcements.plan_early_notices',lambda *_:pytest.fail('Failed collection published'))
    def failed(db,sources,**kwargs):
        with db.transaction() as c:
            run=c.execute("insert into startup_radar.ingestion_runs(status,trigger_type,finished_at) values('FAILED','discovery-test',now()) returning id").fetchone()['id']
        return {'status':'FAILED','id':str(run),'sources':[]}
    result=run_discovery(enabled_discovery,collector=failed)
    assert result['status']=='FAILED' and 'early_notice' not in result


def test_retry_cannot_accept_transport_or_an_injected_clock():
    from radar.discovery import run_discovery
    with pytest.raises(ValueError, match='cannot deliver'):
        run_discovery(None, transport=object(), retry_failed=True)
    with pytest.raises(ValueError, match='database clock'):
        run_discovery(None, at=datetime(2026,10,26,18,tzinfo=SEOUL), retry_failed=True)


def test_cli_rejects_retry_and_delivery_before_loading_database(monkeypatch):
    from radar.cli import main
    monkeypatch.setattr('radar.cli.Database',lambda:pytest.fail('Invalid flags opened a database'))
    with pytest.raises(SystemExit) as error:
        main(['discover','--retry-failed','--deliver'])
    assert error.value.code == 2


def retry_collector(status, calls):
    def collect(db,sources,**kwargs):
        calls.append(kwargs)
        failed = status in ('FAILED','PARTIAL_SUCCESS')
        outcomes = [{'source_slug': 'discovery-k', 'status': 'FAILED' if failed else 'SUCCESS',
                     'failures': [{'kind': 'NETWORK', 'retryable': True}] if failed else []}]
        with db.transaction() as c:
            run=c.execute('insert into startup_radar.ingestion_runs(status,trigger_type,finished_at) '
                          'values(%s,%s,now()) returning id',(status,'retry-fixture')).fetchone()['id']
        return {'status':status,'id':str(run),'sources':outcomes}
    return collect


@pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Explicit test database required')
def test_retry_preserves_previous_slot_and_execution_and_never_plans_or_sends(enabled_discovery,monkeypatch):
    from radar.discovery import run_discovery
    calls=[]
    monkeypatch.setattr('radar.early_announcements.plan_early_notices',lambda *_: {'state':'DISABLED'})
    first=run_discovery(enabled_discovery,collector=retry_collector('PARTIAL_SUCCESS',calls))
    with enabled_discovery.transaction() as c:
        before=c.execute('select to_jsonb(s) value from startup_radar.discovery_slots s').fetchone()['value']
    monkeypatch.setattr('radar.early_announcements.plan_early_notices',lambda *_:pytest.fail('Retry planned a publication'))
    monkeypatch.setattr('radar.early_announcements.announce_early',lambda *_args,**_kw:pytest.fail('Retry delivered'))
    recovered=run_discovery(enabled_discovery,collector=retry_collector('SUCCESS',calls),retry_failed=True)
    assert recovered['status']=='SUCCESS' and recovered['retry_failed']
    assert 'early_notice' not in recovered and 'early_delivery' not in recovered
    assert calls == [
        {'trigger':'daily-discovery','structured_only':True},
        {'trigger':'daily-discovery-retry','structured_only':True},
    ]
    with enabled_discovery.transaction() as c:
        current=c.execute('select * from startup_radar.discovery_slots').fetchone()
        audit=c.execute("select detail from startup_radar.admin_audit where action='DISCOVERY_SLOT_RETRY'").fetchone()['detail']
        assert str(current['execution_id']) == recovered['execution_id']
        assert current['finished_at'] is not None and current['result']['status']=='SUCCESS'
        assert audit['previous_slot']==before
        assert audit['previous_execution']['id']==first['execution_id']
        assert audit['previous_execution']['state']=='PARTIAL_SUCCESS'
        assert audit['replacement_execution_id']==recovered['execution_id']
        assert c.execute('select count(*) n from startup_radar.worker_executions').fetchone()['n']==2
        assert c.execute('select count(*) n from startup_radar.weekly_briefings').fetchone()['n']==0
        assert c.execute('select count(*) n from startup_radar.early_notices').fetchone()['n']==0


@pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Explicit test database required')
def test_a_slot_can_only_be_retried_once_even_if_the_retry_also_fails(enabled_discovery,monkeypatch):
    from radar.discovery import run_discovery
    calls=[]
    monkeypatch.setattr('radar.early_announcements.plan_early_notices',lambda *_: {'state':'DISABLED'})
    first=run_discovery(enabled_discovery,collector=retry_collector('FAILED',calls))
    retried=run_discovery(enabled_discovery,collector=retry_collector('FAILED',calls),retry_failed=True)
    rejected=run_discovery(enabled_discovery,
        collector=lambda *_args,**_kw:pytest.fail('Second retry collected'),retry_failed=True)
    assert first['executed'] and retried['executed']
    assert rejected['state']=='RETRY_LIMIT_REACHED' and not rejected['executed']
    assert len(calls)==2
    with enabled_discovery.transaction() as c:
        assert c.execute("select count(*) n from startup_radar.admin_audit where action='DISCOVERY_SLOT_RETRY'").fetchone()['n']==1
        assert str(c.execute('select execution_id from startup_radar.discovery_slots').fetchone()['execution_id'])==retried['execution_id']


@pytest.mark.parametrize('case,expected',[
    ('slot-unfinished','RETRY_PREVIOUS_EXECUTION_UNFINISHED'),
    ('worker-success','RETRY_PREVIOUS_EXECUTION_NOT_FAILED'),
    ('worker-uncertain','RETRY_PREVIOUS_EXECUTION_NOT_FAILED'),
    ('slot-success','RETRY_SLOT_NOT_FAILED'),
    ('no-source-failure','RETRY_REQUIRES_FAILED_SOURCE'),
])
@pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Explicit test database required')
def test_ineligible_completed_slots_are_never_retried(enabled_discovery,case,expected):
    from radar.discovery import run_discovery
    first=run_discovery(enabled_discovery,collector=retry_collector('FAILED',[]))
    with enabled_discovery.transaction() as c:
        if case=='slot-unfinished':
            c.execute('update startup_radar.discovery_slots set finished_at=null')
        elif case.startswith('worker-'):
            c.execute('update startup_radar.worker_executions set state=%s where id=%s',
                      ('SUCCESS' if case=='worker-success' else 'UNCERTAIN',first['execution_id']))
        elif case=='slot-success':
            c.execute("update startup_radar.discovery_slots set result=jsonb_set(result,'{status}','\"SUCCESS\"')")
        else:
            c.execute("update startup_radar.discovery_slots set result=jsonb_set(result,'{sources}','[]')")
    rejected=run_discovery(enabled_discovery,
        collector=lambda *_args,**_kw:pytest.fail('Ineligible retry collected'),retry_failed=True)
    assert rejected['status']=='FAILED' and rejected['state']==expected
    with enabled_discovery.transaction() as c:
        assert c.execute("select count(*) n from startup_radar.admin_audit where action='DISCOVERY_SLOT_RETRY'").fetchone()['n']==0
        assert str(c.execute('select execution_id from startup_radar.discovery_slots').fetchone()['execution_id'])==first['execution_id']


@pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Explicit test database required')
def test_retry_without_a_slot_does_not_create_one(enabled_discovery):
    from radar.discovery import run_discovery
    result=run_discovery(enabled_discovery,
        collector=lambda *_args,**_kw:pytest.fail('Missing-slot retry collected'),retry_failed=True)
    assert result['state']=='RETRY_SLOT_NOT_FOUND'
    with enabled_discovery.transaction() as c:
        assert c.execute('select count(*) n from startup_radar.discovery_slots').fetchone()['n']==0


@pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Explicit test database required')
def test_inflight_owner_prevents_retry_before_slot_or_audit_changes(enabled_discovery):
    from radar.discovery import run_discovery
    first=run_discovery(enabled_discovery,collector=retry_collector('FAILED',[]))
    with enabled_discovery.transaction() as c:
        c.execute("update startup_radar.worker_executions set state='RUNNING',finished_at=null where id=%s",
                  (first['execution_id'],))
        before=c.execute('select to_jsonb(s) value from startup_radar.discovery_slots s').fetchone()['value']
    rejected=run_discovery(enabled_discovery,
        collector=lambda *_args,**_kw:pytest.fail('In-flight retry collected'),retry_failed=True)
    assert rejected['status']=='FAILED'
    with enabled_discovery.transaction() as c:
        assert c.execute('select to_jsonb(s) value from startup_radar.discovery_slots s').fetchone()['value']==before
        assert c.execute("select count(*) n from startup_radar.admin_audit where action='DISCOVERY_SLOT_RETRY'").fetchone()['n']==0
        assert c.execute('select count(*) n from startup_radar.worker_executions').fetchone()['n']==1


@pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Explicit test database required')
def test_uncaught_collector_failure_still_finalizes_owned_slot(enabled_discovery):
    from radar.discovery import run_discovery
    def broken(*_args,**_kwargs): raise RuntimeError('fixture collection crash')
    result=run_discovery(enabled_discovery,collector=broken)
    assert result['status']=='FAILED' and result['reason']=='RuntimeError'
    with enabled_discovery.transaction() as c:
        slot=c.execute('select * from startup_radar.discovery_slots').fetchone()
        assert slot['finished_at'] is not None and slot['result']['reason']=='RuntimeError'
