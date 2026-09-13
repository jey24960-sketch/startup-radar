import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import psycopg
import pytest
from psycopg.types.json import Jsonb
from radar.models import TeamProfile, apply_preset, update_profile
from radar.member_results import refresh_member_results
from tools.profile_contract import contract
from test_database import db
from test_web_runtime import context

pytestmark=pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Explicit ephemeral database required')

def call(db,user,name,*args):
    with db.transaction(user) as c:
        return c.execute('select public.'+name+'('+','.join(['%s']*len(args))+') result',args).fetchone()['result']

def update(c,changes,preset=None,expected=1,user=None):
    return call(c['db'],user or c['admin'],'gfc_radar_update_profile',c['team']['id'],expected,Jsonb(changes),preset)

def test_profile_contract_and_presets_match_existing_engine(context):
    c=context
    with c['db'].transaction(c['admin']) as con:
        assert con.execute('select startup_radar.profile_contract() value').fetchone()['value']==contract()
        for initial in (TeamProfile(),update_profile(apply_preset(TeamProfile(),0),{'founder_age':22,'business_status':'CORPORATION'})):
            for preset in range(5):
                changes={'has_revenue':None,'student_status':False,'region':'Seoul'}
                expected=update_profile(apply_preset(initial,preset),changes)
                actual=con.execute('select startup_radar.apply_member_profile(%s,%s,%s) value',(Jsonb(initial.model_dump(mode='json')),preset,Jsonb(changes))).fetchone()['value']
                assert TeamProfile.model_validate(actual)==expected

def test_create_idempotency_owner_binding_and_external_denial(context):
    c=context;request=uuid4()
    first=call(c['db'],c['admin'],'gfc_radar_create_team','Stage zero',0,request)
    assert first==call(c['db'],c['admin'],'gfc_radar_create_team','Stage zero',0,request)
    with c['db'].transaction(c['admin']) as con:
        p=con.execute('select * from startup_radar.team_profiles where team_id=%s',(first['id'],)).fetchone()
        assert TeamProfile.model_validate(p['profile'])==apply_preset(TeamProfile(),0)
        assert con.execute('select state from startup_radar.profile_calculation_requests where team_id=%s',(first['id'],)).fetchone()['state']=='PENDING'
        assert con.execute('select count(*) n from startup_radar.team_profile_versions where team_id=%s',(first['id'],)).fetchone()['n']==1
    for user,name in ((c['other'],'Stage zero'),(c['admin'],'Different name')):
        with pytest.raises(psycopg.errors.SerializationFailure):call(c['db'],user,'gfc_radar_create_team',name,0,request)
    outsider=uuid4()
    with c['db'].transaction() as con:
        con.execute('insert into auth.users values(%s)',(outsider,))
        con.execute("insert into public.test_gfc_roles values(%s,'external')",(outsider,))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):call(c['db'],outsider,'gfc_radar_create_team','Denied',0,uuid4())

def test_atomic_history_queue_conflict_and_member_read_only(context):
    c=context;updated=update(c,{'founder_age':None,'student_status':False},0)
    assert updated['version']==2 and updated['calculation_state']=='PENDING'
    assert updated['profile']['founder_age'] is None and updated['profile']['student_status'] is False
    with pytest.raises(psycopg.errors.SerializationFailure):update(c,{'region':'stale'})
    with pytest.raises(psycopg.errors.InsufficientPrivilege):update(c,{},user=c['other'])
    with c['db'].transaction() as con:
        con.execute("insert into startup_radar.team_members(team_id,user_id,role) values(%s,%s,'MEMBER')",(c['team']['id'],c['other']))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):update(c,{},user=c['other'],expected=2)
    with c['db'].transaction(c['admin']) as con:
        rows=con.execute('select version,profile from startup_radar.team_profile_versions where team_id=%s order by version',(c['team']['id'],)).fetchall()
        assert len(rows)==2 and rows[-1]['profile']==updated['profile']
        assert [r['profile_version'] for r in con.execute('select profile_version from startup_radar.profile_calculation_requests where team_id=%s order by profile_version',(c['team']['id'],)).fetchall()]==[1,2]
    refresh_member_results(c['db'])
    with c['db'].transaction(c['admin']) as con:
        assert [r['state'] for r in con.execute('select state from startup_radar.profile_calculation_requests where team_id=%s order by profile_version',(c['team']['id'],)).fetchall()]==['SUPERSEDED','SUCCESS']

def test_invalid_inputs_and_raw_write_cannot_skip_history(context):
    c=context
    invalid=[{'founder_age':121},{'founder_age':True},{'student_status':'false'},{'team_size':0},{'revenue':-1},
             {'business_registration_date':'2026-02-30'},{'age_band':[30,20]},{'age_band':['1',20]},
             {'preferred_program_types':[1]},{'assumed_fields':[]},{'preset':4},{'business_status_options':[]},{'unsupported':True}]
    for changes in invalid:
        with pytest.raises(psycopg.errors.InvalidParameterValue):update(c,changes)
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        with c['db'].transaction(c['admin']) as con:con.execute("update startup_radar.team_profiles set profile='{}' where team_id=%s",(c['team']['id'],))
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        with c['db'].transaction(c['admin']) as con:con.execute("insert into startup_radar.team_profile_versions(team_id,version,profile) values(%s,50,'{}')",(c['team']['id'],))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with c['db'].transaction(c['admin']) as con:con.execute("update startup_radar.profile_calculation_requests set state='SUCCESS' where team_id=%s",(c['team']['id'],))
    with c['db'].transaction(c['admin']) as con:
        assert con.execute('select version from startup_radar.team_profiles where team_id=%s',(c['team']['id'],)).fetchone()['version']==1

def test_simultaneous_saves_allow_one_version_and_one_request(context):
    c=context
    def save(region):
        try:return update(c,{'region':region})['version']
        except psycopg.errors.SerializationFailure:return 'CONFLICT'
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(save,['Seoul','Busan']))
    assert sorted(map(str,results))==['2','CONFLICT']
    with c['db'].transaction() as con:
        assert con.execute('select count(*) n from startup_radar.profile_calculation_requests where team_id=%s',(c['team']['id'],)).fetchone()['n']==2

def test_queue_failure_rolls_back_profile_and_history(context):
    c=context
    with c['db'].transaction() as con:
        con.execute('alter table startup_radar.profile_calculation_requests add constraint fixture_queue_failure check(profile_version<2)')
        try:
            with pytest.raises(psycopg.errors.CheckViolation):
                with con.transaction():
                    con.execute('set local role authenticated')
                    con.execute("select set_config('request.jwt.claim.sub',%s,true)",(str(c['admin']),))
                    con.execute("select public.gfc_radar_update_profile(%s,1,'{}')",(c['team']['id'],))
            assert con.execute('select version from startup_radar.team_profiles where team_id=%s',(c['team']['id'],)).fetchone()['version']==1
            assert con.execute('select count(*) n from startup_radar.team_profile_versions where team_id=%s',(c['team']['id'],)).fetchone()['n']==1
        finally:con.execute('alter table startup_radar.profile_calculation_requests drop constraint fixture_queue_failure')

def test_edit_during_worker_preserves_new_request_until_next_refresh(context,monkeypatch):
    c=context
    import radar.member_results as worker
    original=worker.evaluate;edited=False
    def edit_once(*args,**kwargs):
        nonlocal edited
        if not edited:
            edited=True;update(c,{'region':'New profile'})
        return original(*args,**kwargs)
    monkeypatch.setattr(worker,'evaluate',edit_once)
    refresh_member_results(c['db'])
    with c['db'].transaction(c['admin']) as con:
        rows=con.execute('select state from startup_radar.profile_calculation_requests where team_id=%s order by profile_version',(c['team']['id'],)).fetchall()
        assert [r['state'] for r in rows]==['SUPERSEDED','PENDING']
    refresh_member_results(c['db'])
    with c['db'].transaction(c['admin']) as con:
        assert con.execute('select state from startup_radar.profile_calculation_requests where team_id=%s and profile_version=2',(c['team']['id'],)).fetchone()['state']=='SUCCESS'
