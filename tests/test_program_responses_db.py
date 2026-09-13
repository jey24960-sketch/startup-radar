import os
from uuid import uuid4
import psycopg
import pytest
from psycopg.types.json import Jsonb
from radar.member_results import refresh_member_results
from test_database import db
from test_web_runtime import context
from test_member_results import rpc,detail
from test_program_questions import question

pytestmark=pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Explicit ephemeral database required')


def setup(c):
    p=c['program'].model_copy(deep=True);p.requirements.append(question())
    c['saved']=c['db'].save_program(p,c['source'],'first',p.official_url,{},'Attendance required')
    return c['saved']['version_id']


def answer(c,version,values,revision=0,user=None,team=None):
    return rpc(c,'gfc_radar_program_responses',(team or c['team']['id'],version,Jsonb(values),revision),user)


def test_answers_invalidate_only_the_selected_team_version_and_can_return_to_unknown(context):
    c=context;version=setup(c);refresh_member_results(c['db'])
    assert detail(c,c['team']['id'])['eligibility']['status']=='NEEDS_INFO'
    first=answer(c,version,{'offline':True})
    assert first['revision']==1
    assert detail(c,c['team']['id'])['calculation_state']=='PENDING'
    assert detail(c)['eligibility']['status']=='NEEDS_INFO'
    assert refresh_member_results(c['db'])['computed']==1
    assert detail(c,c['team']['id'])['eligibility']['status']=='ELIGIBLE'
    assert answer(c,version,{'offline':True})['changed'] is False
    with pytest.raises(psycopg.errors.SerializationFailure):answer(c,version,{'offline':False},0)
    answer(c,version,{'offline':False},1);refresh_member_results(c['db'])
    assert detail(c,c['team']['id'])['eligibility']['status']=='INELIGIBLE'
    answer(c,version,{'offline':None},2);refresh_member_results(c['db'])
    assert detail(c,c['team']['id'])['eligibility']['status']=='NEEDS_INFO'
    with c['db'].transaction() as connection:
        assert connection.execute('select version from startup_radar.team_profiles where team_id=%s',(c['team']['id'],)).fetchone()['version']==1


def test_answers_reject_foreign_team_external_user_viewer_direct_write_and_old_version(context):
    c=context;version=setup(c)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):answer(c,version,{'offline':True},team=c['other_team']['id'])
    outsider,viewer=uuid4(),uuid4()
    with c['db'].transaction() as connection:
        connection.execute('insert into auth.users values(%s),(%s)',(outsider,viewer))
        connection.execute("insert into public.test_gfc_roles values(%s,'external'),(%s,'member')",(outsider,viewer))
        connection.execute("insert into startup_radar.team_members(team_id,user_id,role) values(%s,%s,'MEMBER')",(c['team']['id'],viewer))
    for user in (outsider,viewer):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):answer(c,version,{'offline':True},user=user)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with c['db'].transaction(c['admin']) as connection:
            connection.execute('insert into startup_radar.team_program_responses(team_id,program_version_id,updated_by) values(%s,%s,%s)',(c['team']['id'],version,c['admin']))
    c['db'].save_program(c['program'],c['source'],'first',c['program'].official_url,{},'Changed fixture')
    with pytest.raises(psycopg.errors.SerializationFailure):answer(c,version,{'offline':True})


@pytest.mark.parametrize('value',[{'offline':'true'},{'unknown':True},{'offline':1}])
def test_answers_reject_invalid_payload(context,value):
    c=context;version=setup(c)
    with pytest.raises(psycopg.errors.InvalidParameterValue):answer(c,version,value)


def test_answer_changed_during_calculation_remains_pending(context,monkeypatch):
    import radar.member_results as results
    c=context;version=setup(c)
    answer(c,version,{'offline':True})
    original=results.evaluate
    changed=False
    def concurrent_answer(*args,**kwargs):
        nonlocal changed
        if not changed and kwargs.get('program_responses')=={'offline':True}:
            changed=True
            answer(c,version,{'offline':False},1)
        return original(*args,**kwargs)
    monkeypatch.setattr(results,'evaluate',concurrent_answer)
    refresh_member_results(c['db'])
    assert changed and detail(c,c['team']['id'])['calculation_state']=='PENDING'
    with c['db'].transaction() as connection:
        assert connection.execute('select state from startup_radar.profile_calculation_requests where team_id=%s',
                                  (c['team']['id'],)).fetchone()['state']=='PENDING'
    refresh_member_results(c['db'])
    assert detail(c,c['team']['id'])['eligibility']['status']=='INELIGIBLE'
