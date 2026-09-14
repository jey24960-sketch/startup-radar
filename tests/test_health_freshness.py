"""Independent clocks and stale-state projections against native PostgreSQL."""
import os
from datetime import datetime, timedelta
import pytest
import psycopg
from psycopg.types.json import Jsonb
from radar.member_results import refresh_member_results
from radar.services import health
from radar.quality import quality_report
from test_database import db
from test_web_runtime import context
from test_member_results import rpc, detail

pytestmark=pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Explicit ephemeral database required')


def own_calculation(c):
    teams=rpc(c,'gfc_radar_me')['teams']
    return next(t['calculation'] for t in teams if t['id']==str(c['team']['id']))


def test_thresholds_and_never_seen_are_not_healthy(context):
    c=context
    with c['db'].transaction() as con:
        row=con.execute("select startup_radar.freshness(null) unknown, startup_radar.freshness(now()) fresh, "
            "startup_radar.freshness(now()-interval '24 hours') boundary, "
            "startup_radar.freshness(now()-interval '24 hours 1 second') warning, "
            "startup_radar.freshness(now()-interval '48 hours 1 second') incident, "
            "startup_radar.freshness(now()+interval '1 day') future").fetchone()
        assert row==dict(unknown='UNKNOWN',fresh='FRESH',boundary='FRESH',warning='WARNING',incident='INCIDENT',future='UNKNOWN')
    snapshot=health(c['db'])
    assert snapshot['sources'][0]['freshness']=='UNKNOWN'
    assert snapshot['successful_sources']==0
    assert snapshot['notifications']['enabled_channels']==snapshot['notifications']['deliverable_channels']==0
    assert snapshot['notifications']['last_confirmed_receipt_at'] is None
    assert snapshot['notifications']['receipt_origin_verified'] is False


def test_refresh_success_never_masks_stale_ingestion_or_historical_document_counts(context):
    c=context
    with c['db'].transaction() as con:
        con.execute("insert into startup_radar.documents(program_version_id,original_url,filename,fetch_status,extraction_status,error_kind) "
            "values(%s,'https://example.org/old.pdf','old.pdf','SUCCESS','FAILED','DOCUMENT_PARSE')",(c['saved']['version_id'],))
        run=con.execute("insert into startup_radar.ingestion_runs(status,trigger_type) values('SUCCESS','fixture') returning id").fetchone()['id']
        con.execute("insert into startup_radar.source_run_results(run_id,source_id,status,coverage) values(%s,%s,'SUCCESS',%s)",
            (run,c['source'],Jsonb({'pages_requested':1,'advertised_records':40,'fetched_unique_records':20,'pagination_complete':False,'api_key':'PRIVATE_CANARY'})))
        con.execute("update startup_radar.sources set last_attempted_at=now(),last_successful_full_scan_at=now()-interval '49 hours',"
            "last_persisted_at=now()-interval '1 hour',last_source_observation_at=now(),last_failure_at=now()-interval '30 minutes',"
            "last_failure_reason='DNS_ERROR' where id=%s",(c['source'],))
    changed=c['program'].model_copy(deep=True);changed.application_end_at+=timedelta(days=1)
    c['db'].save_program(changed,c['source'],'first',changed.official_url,{},'Updated fixture',documents=[{
        'original_url':'https://example.org/new.pdf','filename':'new.pdf','fetch_status':'SUCCESS',
        'extraction_status':'SUCCESS','extracted_text':'Verified fixture text','content_hash':'fixture'}])
    refresh_member_results(c['db'])
    snapshot=rpc(c,'gfc_radar_health')
    assert snapshot['calculation']['state']=='SUCCESS' and snapshot['calculation']['last_successful_refresh_at']
    assert snapshot['successful_sources']==0 and snapshot['sources'][0]['freshness']=='INCIDENT'
    assert snapshot['sources'][0]['observation_freshness']=='FRESH'
    assert snapshot['sources'][0]['last_failure_reason']=='DNS_ERROR'
    assert snapshot['sources'][0]['coverage']['pagination_complete'] is False
    assert 'PRIVATE_CANARY' not in str(snapshot)
    docs=snapshot['documents']
    assert (docs['current_total'],docs['current_failures'],docs['historical_total'],docs['historical_failures'])==(1,0,1,1)
    assert snapshot['failure_counts']['documents']==0
    assert health(c['db'],c['admin'])['documents']==docs


def test_exact_version_observation_and_dynamic_stale_quality_preserve_facts(context):
    c=context;old_id=c['saved']['version_id']
    with c['db'].transaction() as con:
        con.execute("update startup_radar.program_versions set last_observed_at=now()-interval '50 hours' where id=%s",(old_id,))
        old_time=con.execute('select last_observed_at from startup_radar.program_versions where id=%s',(old_id,)).fetchone()['last_observed_at']
        con.execute("update startup_radar.program_quality set state='ACTIONABLE',reasons='{}' where program_version_id=%s",(old_id,))
    old=detail(c,version=old_id)
    assert old['source_freshness']=='INCIDENT' and old['quality']['state']=='NEEDS_REVIEW'
    assert old['quality']['reasons']==['STALE_SOURCE']
    assert old['facts']['evidence_complete'] is True
    assert quality_report(c['db'])['counts']['NEEDS_REVIEW']==1
    changed=c['program'].model_copy(deep=True);changed.application_end_at+=timedelta(days=2)
    saved=c['db'].save_program(changed,c['source'],'first',changed.official_url,{},'New version observation')
    assert saved['version_id']!=old_id
    current=detail(c)
    assert current['source_freshness']=='FRESH'
    assert datetime.fromisoformat(detail(c,version=old_id)['source_observed_at'])==old_time
    assert current['version_created_at']==current['updated_at']
    with c['db'].transaction(c['other']) as con:
        assert con.execute('select count(*) n from startup_radar.program_source_snapshots').fetchone()['n']==0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with con.transaction():con.execute('select startup_radar.health_snapshot()')


def test_identical_observation_refreshes_exact_version_without_rewriting_snapshot(context):
    c=context
    with c['db'].transaction() as con:
        con.execute("update startup_radar.program_versions set last_observed_at=now()-interval '50 hours' where id=%s",(c['saved']['version_id'],))
        before=con.execute('select id,observed_at,observation_hash from startup_radar.program_source_snapshots order by id').fetchall()
    assert detail(c)['source_freshness']=='INCIDENT'
    saved=c['db'].save_program(c['program'],c['source'],'first',c['program'].official_url,{},'Fixture only')
    assert saved['version_id']==c['saved']['version_id'] and saved['event'] is None
    assert detail(c)['source_freshness']=='FRESH'
    with c['db'].transaction() as con:
        assert con.execute('select id,observed_at,observation_hash from startup_radar.program_source_snapshots order by id').fetchall()==before


def test_profile_queue_states_and_failed_refresh_preserve_last_success(context,monkeypatch):
    c=context
    assert own_calculation(c)['state']=='QUEUED'
    with c['db'].transaction() as con:
        con.execute("update startup_radar.profile_calculation_requests set requested_at=now()-interval '91 minutes',state='RUNNING',started_at=now() where team_id=%s",(c['team']['id'],))
    running=own_calculation(c)
    assert running['state']=='CALCULATING' and running['delayed'] is True and running['target_verified'] is False
    refresh_member_results(c['db'])
    ready=own_calculation(c)
    assert ready['state']=='READY' and ready['current_results']==ready['current_programs']==1
    before=rpc(c,'gfc_radar_health')['calculation']['last_successful_refresh_at']
    changed=rpc(c,'gfc_radar_update_profile',(c['team']['id'],1,Jsonb({'region':'Seoul'}),None))
    assert changed['calculation']['state']=='QUEUED' and changed['calculation']['current_results']==0
    assert rpc(c,'gfc_radar_programs',(c['team']['id'],))['calculation']['state']=='QUEUED'
    import radar.member_results as worker
    def fail(*args,**kwargs):raise RuntimeError('PRIVATE_ENGINE_CANARY')
    monkeypatch.setattr(worker,'evaluate',fail)
    with pytest.raises(RuntimeError):refresh_member_results(c['db'])
    assert own_calculation(c)['state']=='FAILED'
    after=rpc(c,'gfc_radar_health')['calculation']
    assert after['last_successful_refresh_at']==before
    assert after['state']=='FAILED' and after['last_failure_at'] and after['last_failure_reason']=='RuntimeError'
    assert 'PRIVATE_ENGINE_CANARY' not in str(after)


def test_recovery_projection_counts_latest_attempt_without_erasing_failure_history(context):
    c=context
    with c['db'].transaction() as con:
        con.execute("insert into startup_radar.schedule_claims(task_key,kind,state) values('fixture-failed','INGEST','FAILED')")
        con.execute("insert into startup_radar.schedule_task_attempts(task_key,kind,state,attempt_number,reason_code) values('fixture-failed','INGEST','FAILED_TERMINAL',1,'ROBOTS_DISALLOWED')")
    unresolved=rpc(c,'gfc_radar_health')['schedule_attempts']
    assert unresolved['unresolved']==1
    assert unresolved['items'][0]['recovery']=='FIX_CAUSE_THEN_AUDITED_RETRY'
    with c['db'].transaction() as con:
        con.execute("insert into startup_radar.schedule_task_attempts(task_key,kind,state,attempt_number) values('fixture-failed','INGEST','SUCCESS',2)")
    recovered=rpc(c,'gfc_radar_health')['schedule_attempts']
    assert recovered['unresolved']==0 and recovered['retry_attempts']==1 and recovered['items']==[]
    with c['db'].transaction() as con:
        assert con.execute("select count(*) n from startup_radar.schedule_task_attempts where state='FAILED_TERMINAL'").fetchone()['n']==1
