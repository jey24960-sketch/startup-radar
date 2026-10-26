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
