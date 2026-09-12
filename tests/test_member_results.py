import os
import json
from pathlib import Path
import subprocess
import sys
from datetime import timedelta
from contextlib import contextmanager
from uuid import uuid4
import psycopg
import pytest
from psycopg.types.json import Jsonb
from core.clock import now
from radar.member_results import refresh_member_results
from radar.models import TeamProfile, update_profile
from radar.scheduler import run_job
from test_database import db
from test_web_runtime import context

pytestmark=pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Explicit ephemeral database required')

def rpc(c, name, args=(), user=None):
    with c['db'].transaction(user or c['admin']) as connection:
        return connection.execute('select public.'+name+'('+','.join(['%s']*len(args))+') as result',args).fetchone()['result']

def detail(c, team=None, version=None, user=None):
    return rpc(c,'gfc_radar_program_detail',(c['saved']['program_id'],team,None,version),user)

def test_batch_presets_team_isolation_and_no_calculation_on_reads(context):
    c=context
    pending=detail(c)
    assert pending['calculation_state'] in ('PENDING','FAILED') and pending['eligibility'] is None
    batch=run_job(c['db'],'REFRESH')
    assert batch['status']=='SUCCESS' and batch['computed']==7 and batch['delivery']=='DISABLED'
    with c['db'].transaction() as con:
        assert con.execute('select count(*) from startup_radar.notification_items').fetchone()['count']==0
    for preset in range(5):
        page=rpc(c,'gfc_radar_programs',(None,preset))
        assert page['total']==1 and page['pending_count']==0
        assert page['items'][0]['calculation_state']=='READY'
    assert detail(c,c['team']['id'])['eligibility']['status']=='ELIGIBLE'
    assert detail(c,c['other_team']['id'],user=c['other'])['eligibility']['status']=='INELIGIBLE'
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        detail(c,c['other_team']['id'])
    outsider=uuid4()
    with c['db'].transaction() as con:
        con.execute('insert into auth.users values(%s)',(outsider,))
        con.execute("insert into public.test_gfc_roles values(%s,'external')",(outsider,))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        rpc(c,'gfc_radar_programs',(),outsider)
    assert refresh_member_results(c['db'])['computed']==0

def test_profile_program_day_and_generation_changes_hide_stale_results(context):
    c=context;refresh_member_results(c['db'])
    profile=update_profile(TeamProfile.model_validate(c['team']['profile']),{'business_status':'CORPORATION'}) if 'profile' in c['team'] else TeamProfile(business_status='CORPORATION')
    c['db'].save_profile(c['team']['id'],profile,c['admin'],1)
    pending=detail(c,c['team']['id'])
    assert pending['calculation_state']=='PENDING' and pending['eligibility'] is None and pending['recommendation'] is None
    assert refresh_member_results(c['db'])['computed']==1
    assert detail(c,c['team']['id'])['eligibility']['status']=='INELIGIBLE'
    with c['db'].transaction() as con:
        con.execute("update startup_radar.member_program_results set evaluated_on=evaluated_on-1 where scope_key='preset:0'")
    assert detail(c)['eligibility'] is None
    assert refresh_member_results(c['db'])['computed']==1
    with c['db'].transaction() as con:
        con.execute("update startup_radar.member_read_state set generation='new-engine' where singleton")
    assert detail(c)['eligibility'] is None
    refresh_member_results(c['db'])
    updated=c['program'].model_copy(deep=True);updated.application_end_at+=timedelta(days=3)
    c['db'].save_program(updated,c['source'],'first',updated.official_url,{},'Changed deadline')
    assert detail(c)['calculation_state']=='PENDING'
    assert detail(c,version=c['saved']['version_id'])['calculation_state']=='READY'


def test_source_review_is_version_scoped_sanitized_and_member_authorized(context):
    c=context
    metadata={'review_flags':[{'kind':'FUTURE_COMMITMENT_NOT_REPRESENTED','quote':'입주 후 사업자등록 필요','private_debug':'must-not-leak'},
                              {'kind':'unknown-internal-code','quotes':['x'*600,17,None,''], 'secret':'must-not-leak'}],
              'private_provider_debug':'must-not-leak'}
    c['db'].save_program(c['program'],c['source'],'first',c['program'].official_url,{},'Fixture only',extraction_metadata=metadata)
    member=c['other']
    with c['db'].transaction(member) as con:
        assert con.execute('select count(*) n from startup_radar.program_source_snapshots').fetchone()['n']==0
    current=detail(c,user=member)
    assert current['calculation_state'] in ('PENDING','FAILED')
    findings={f['kind']:f for f in current['source_review']}
    assert findings['FUTURE_COMMITMENT_NOT_REPRESENTED']['quotes']==['입주 후 사업자등록 필요']
    assert findings['UNCLASSIFIED_REVIEW']['quotes']==['x'*500]
    assert all(set(f)=={'kind','quotes','source_url'} for f in findings.values())
    assert 'must-not-leak' not in json.dumps(current['source_review'])
    updated=c['program'].model_copy(deep=True);updated.application_end_at+=timedelta(days=1)
    c['db'].save_program(updated,c['source'],'first',updated.official_url,{},'Changed conditions',extraction_metadata={'review_flags':[]})
    assert detail(c,user=member)['source_review']==[]
    assert detail(c,version=c['saved']['version_id'],user=member)['source_review']==current['source_review']
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        detail(c,c['team']['id'],user=member)
    with c['db'].transaction() as con:
        con.execute("insert into public.test_gfc_roles values(%s,'external')",(member,))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        detail(c,user=member)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with c['db'].transaction(member) as con:
            con.execute('select startup_radar.member_source_review(%s)',(c['saved']['version_id'],))
    with c['db'].transaction() as con:
        assert not con.execute("select has_function_privilege('anon','startup_radar.member_source_review(uuid)','EXECUTE') allowed").fetchone()['allowed']


def test_source_review_uses_latest_observation_and_tolerates_invalid_metadata(context):
    c=context
    for flags in ([{'kind':'BUSINESS_STATUS_NOT_EXPLICIT','quotes':['a','a','b','c','d']}], {'malformed':'object'}):
        c['db'].save_program(c['program'],c['source'],'first',c['program'].official_url,{},'Fixture only',extraction_metadata={'review_flags':flags})
        findings=detail(c,user=c['other'])['source_review']
        if isinstance(flags,list):assert findings[0]['quotes']==['a','b','c']
        else:assert findings==[]


def test_member_cache_survives_new_worker_processes(context):
    code = '''
import json, os
from datetime import datetime
from radar.database import Database
from radar.scheduler import run_job
import radar.member_results as worker
worker.now = lambda: datetime.fromisoformat(os.environ['RADAR_TEST_FIXED_NOW'])
print(json.dumps(run_job(Database(os.environ['TEST_DATABASE_URL']), 'REFRESH')))
'''
    fixed_now = now().isoformat()
    results = [json.loads(subprocess.check_output(
        [sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, 'PYTHONHASHSEED': seed, 'RADAR_TEST_FIXED_NOW': fixed_now},
        text=True, encoding='utf-8', timeout=60
    )) for seed in ('1', '2', '3')]
    assert [(r['computed'], r['reused']) for r in results] == [(7, 0), (0, 7), (0, 7)]
    assert all(r['status'] == 'SUCCESS' and r['delivery'] == 'DISABLED' for r in results)


def add_history(c, last_version):
    with c['db'].transaction() as con:
        con.execute('insert into startup_radar.program_versions(program_id,version,content_hash,normalized,raw_text,evidence_complete) '
            'select program_id,n,md5(content_hash || n::text),normalized,raw_text,evidence_complete '
            'from startup_radar.program_versions cross join generate_series(2,%s) n where id=%s',
            (last_version,c['saved']['version_id']))


def test_bounded_cache_lookup_pages_and_mixed_stale_results(context, monkeypatch):
    c=context
    add_history(c,101)
    db=c['db'];transaction=db.transaction;lookup_sizes=[]
    class TracedConnection:
        def __init__(self, connection):self.connection=connection
        def execute(self, sql, params=None):
            if sql.startswith('select program_version_id from startup_radar.member_program_results'):
                lookup_sizes.append(len(params[1]))
            return self.connection.execute(sql,params)
    @contextmanager
    def traced(*args,**kwargs):
        with transaction(*args,**kwargs) as con:yield TracedConnection(con)
    monkeypatch.setattr(db,'transaction',traced)
    first=refresh_member_results(db)
    assert (first['computed'],first['reused'])==(707,0)
    assert sorted(lookup_sizes)==[1]*7+[100]*7
    lookup_sizes.clear()
    with db.transaction() as con:
        version=c['saved']['version_id']
        con.execute("update startup_radar.member_program_results set evaluated_on=evaluated_on-1 where scope_key='preset:0' and program_version_id=%s",(version,))
        con.execute("update startup_radar.member_program_results set generation='obsolete' where scope_key='preset:1' and program_version_id=%s",(version,))
        con.execute("update startup_radar.member_program_results set profile_snapshot='{}' where scope_key='preset:2' and program_version_id=%s",(version,))
        con.execute("delete from startup_radar.member_program_results where scope_key='preset:3' and program_version_id=%s",(version,))
        con.execute('update startup_radar.member_program_results set profile_version=profile_version+1 where team_id=%s and program_version_id=%s',(c['team']['id'],version))
    second=refresh_member_results(db)
    assert (second['computed'],second['reused'])==(5,702)
    assert sorted(lookup_sizes)==[1]*7+[100]*7
    assert detail(c,c['team']['id'])['eligibility']['status']=='ELIGIBLE'
    assert detail(c,c['other_team']['id'],user=c['other'])['eligibility']['status']=='INELIGIBLE'


def test_batched_cache_rechecks_seoul_day_inside_a_page(context,monkeypatch):
    import radar.member_results as worker
    c=context;add_history(c,2)
    before=now().replace(hour=23,minute=59,second=59,microsecond=0)
    after=before+timedelta(seconds=2)
    monkeypatch.setattr(worker,'now',lambda:before)
    assert refresh_member_results(c['db'])['computed']==14
    calls=iter([before])
    monkeypatch.setattr(worker,'now',lambda:next(calls,after))
    result=refresh_member_results(c['db'])
    assert (result['computed'],result['reused'])==(13,1)
    with c['db'].transaction() as con:
        dates=con.execute('select evaluated_on,count(*) n from startup_radar.member_program_results group by evaluated_on order by evaluated_on').fetchall()
    assert [(r['evaluated_on'],r['n']) for r in dates]==[(before.date(),1),(after.date(),13)]

def test_historical_facts_document_failures_and_foreign_version(context):
    c=context;updated=c['program'].model_copy(deep=True)
    updated.application_end_at+=timedelta(days=2);updated.evidence_complete=False
    saved=c['db'].save_program(updated,c['source'],'first',updated.official_url,{},'Changed fixture',documents=[{
        'original_url':'https://example.org/broken.hwp','filename':'broken.hwp','content_hash':'broken',
        'fetch_status':'SUCCESS','extraction_status':'FAILED','error_kind':'DOCUMENT_PARSE'}])
    refresh_member_results(c['db'])
    latest=detail(c);old=detail(c,version=c['saved']['version_id'])
    assert [v['version'] for v in latest['versions']]==[2,1]
    assert latest['documents'][0]['extraction_status']=='FAILED' and old['documents']==[]
    assert latest['eligibility']['status']=='UNVERIFIABLE' and old['eligibility']['status']=='ELIGIBLE'
    assert latest['facts']['application_end_at']!=old['facts']['application_end_at']
    another=updated.model_copy(deep=True);another.official_url+='/different'
    foreign=c['db'].save_program(another,c['source'],'other',another.official_url,{},'Other fixture')
    with pytest.raises(psycopg.errors.NoDataFound):detail(c,version=foreign['version_id'])

def test_sql_filters_pagination_live_deadline_and_failed_refresh(context,monkeypatch):
    c=context;refresh_member_results(c['db'])
    assert rpc(c,'gfc_radar_programs',(None,0,'no matching title'))['total']==0
    assert rpc(c,'gfc_radar_programs',(None,0,'',None,None,None,False,False,1,1))['items']==[]
    with pytest.raises(psycopg.errors.InvalidParameterValue):rpc(c,'gfc_radar_programs',(None,99))
    with pytest.raises(psycopg.errors.InvalidParameterValue):rpc(c,'gfc_radar_programs',(None,0,'',None,None,None,False,False,101))
    # Advance within the same Seoul day past a real deadline without invalidating
    # the cached computation: SQL must still suppress the recommendation.
    with c['db'].transaction() as con:
        con.execute("update startup_radar.program_versions set normalized=jsonb_set(normalized,'{application_end_at}',to_jsonb((now()-interval '1 minute')::text)) where id=%s",(c['saved']['version_id'],))
        con.execute("update startup_radar.programs set application_end_at=now()-interval '1 minute' where id=%s",(c['saved']['program_id'],))
    assert detail(c)['status']=='CLOSED' and detail(c)['recommendation'] is None
    assert rpc(c,'gfc_radar_programs')['total']==0
    with c['db'].transaction() as con:con.execute('truncate startup_radar.member_program_results')
    import radar.member_results as worker
    def fail(*args,**kwargs):raise RuntimeError('Synthetic engine error')
    monkeypatch.setattr(worker,'evaluate',fail)
    assert run_job(c['db'],'REFRESH')['status']=='FAILED'
    failed=detail(c)
    assert failed['calculation_state']=='FAILED' and failed['eligibility'] is None
