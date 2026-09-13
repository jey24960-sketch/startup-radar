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


def notification_context(c):
    from radar.recommendations import refresh_recommendations
    version=setup(c)
    answer(c,version,{'offline':True})
    refresh_recommendations(c['db'])
    with c['db'].transaction() as connection:
        sub=connection.execute('insert into startup_radar.telegram_subscriptions(team_id,chat_id,high_fit_threshold) values(%s,%s,0) returning id',
            (c['team']['id'],'fixture-channel')).fetchone()['id']
    return version,sub


@pytest.mark.parametrize('kind',['HIGH_FIT','REMINDER'])
def test_notifications_use_confirmed_program_answers(context,kind):
    from unittest.mock import Mock
    from radar.notifications import plan_notifications,deliver_pending
    c=context;version,sub=notification_context(c)
    assert plan_notifications(c['db'],kind,subscription_id=sub)==1
    sender=Mock();sender.send.return_value={'state':'DELIVERED','receipt':{'message_id':901}}
    assert deliver_pending(c['db'],sender,kind,subscription_id=sub)['delivered']==1
    sender.send.assert_called_once()
    assert '지원 가능 여부: 지원 가능' in sender.send.call_args.args[1]
    assert plan_notifications(c['db'],kind,subscription_id=sub)==0


@pytest.mark.parametrize('changed',[{'offline':False},{'offline':None}])
def test_changed_answers_cancel_prepared_notification_without_send(context,changed):
    from unittest.mock import Mock
    from radar.notifications import plan_notifications,deliver_pending
    c=context;version,sub=notification_context(c)
    assert plan_notifications(c['db'],'HIGH_FIT',subscription_id=sub)==1
    answer(c,version,changed,1)
    sender=Mock()
    result=deliver_pending(c['db'],sender,'HIGH_FIT',subscription_id=sub)
    assert result['cancelled']==1 and result['delivered']==0
    sender.send.assert_not_called()


def test_digest_recomputes_score_and_explains_unknown_program_answers(context):
    from radar.notifications import plan_notifications
    c=context;version,sub=notification_context(c)
    answer(c,version,{'offline':None},1)
    assert plan_notifications(c['db'],'DIGEST',subscription_id=sub)==1
    with c['db'].transaction() as connection:
        item=connection.execute('select payload from startup_radar.notification_items where subscription_id=%s',(sub,)).fetchone()['payload']
        original=connection.execute('select score from startup_radar.recommendations where team_id=%s order by created_at desc limit 1',(c['team']['id'],)).fetchone()['score']
    assert item['eligibility']=='NEEDS_INFO' and item['score']<original
    assert '필요 확인:' in item['text'] and item['response_snapshot']=={}


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
