import os
from uuid import uuid4
from unittest.mock import Mock
import pytest
from radar.notifications import plan_notifications,deliver_pending,message,TelegramTransport
from radar.models import Program,EligibilityResult
from tools.telegram_ledger_check import require_simulated_validation
from test_database import db
from test_web_runtime import context
from test_settings_rpc import prefs,ON
from radar.auth import authenticated_user
from radar.recommendations import refresh_recommendations


def test_deep_link_has_only_opportunity_identity_and_safe_external_links(monkeypatch):
    monkeypatch.setenv('RADAR_MEMBER_NOTICE_URL','https://www.gfc-startup.com/notice')
    p=Program(title='Fixture',organization='Fixture',official_url='https://user:password@example.org',application_url='https://apply.example.org/form')
    pid=uuid4()
    text=message(p,'Fixture',EligibilityResult(status='NEEDS_INFO'),70,'Fixture','DIGEST',program_id=pid)
    assert f'https://www.gfc-startup.com/notice/radar/{pid}' in text
    assert 'https://apply.example.org/form' in text and 'password' not in text and 'team_id' not in text
    monkeypatch.setenv('RADAR_MEMBER_NOTICE_URL','https://www.gfc-startup.com/notice?team_id=private')
    with pytest.raises(ValueError):message(p,'Fixture',EligibilityResult(status='NEEDS_INFO'),70,'Fixture','DIGEST',program_id=pid)


def test_legacy_validation_refuses_real_transport_without_touching_database():
    database=Mock()
    with pytest.raises(ValueError,match='cannot activate'):require_simulated_validation(database,TelegramTransport)
    database.transaction.assert_not_called()


def test_telegram_forbidden_is_channel_failure_without_raw_error_leak(monkeypatch):
    response=Mock(status_code=403);response.json.return_value={'ok':False,'description':'PRIVATE_DIAGNOSTIC'}
    monkeypatch.setattr('radar.notifications.requests.post',lambda *args,**kwargs:response)
    result=TelegramTransport('FIXTURE_ONLY').send('FIXTURE','Fixture')
    assert result['state']=='FAILED' and result['channel_health']=='BLOCKED'
    assert 'PRIVATE_DIAGNOSTIC' not in str(result)


@pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Explicit ephemeral database required')
def test_unknown_blocked_suspended_and_user_disabled_are_distinct(context):
    c=context
    with c['db'].transaction() as con:
        sid=con.execute("insert into startup_radar.telegram_subscriptions(team_id,chat_id,enabled) values(%s,'FIXTURE',false) returning id",(c['team']['id'],)).fetchone()['id']
    initial=prefs(c,changes=ON)
    assert initial['bound'] and not initial['connected'] and not initial['deliverable']
    sub=initial['subscriptions'][0]
    assert sub['user_enabled'] and sub['admin_suspended'] and sub['channel_health']=='UNVERIFIED'
    config={'team_id':str(c['team']['id']),'chat_id':'FIXTURE','enabled':False,'channel_health':'HEALTHY','note':'Fixture verified channel permissions'}
    assert c['client'].put('/api/admin/subscriptions',json=config).status_code==200
    assert prefs(c)['connected'] and not prefs(c)['deliverable']
    assert prefs(c,changes=ON)['subscriptions'][0]['admin_suspended']
    config['enabled']=True
    assert c['client'].put('/api/admin/subscriptions',json=config).status_code==200
    assert prefs(c)['deliverable']
    assert not prefs(c,changes={**ON,'enabled':False})['deliverable']
    config['channel_health']='BLOCKED'
    assert c['client'].put('/api/admin/subscriptions',json=config).status_code==200
    assert not prefs(c,changes=ON)['deliverable']
    assert prefs(c)['subscriptions'][0]['channel_health']=='BLOCKED'
    c['app'].dependency_overrides[authenticated_user]=lambda:c['other']
    assert c['client'].put('/api/admin/subscriptions',json=config).status_code==403
    with c['db'].transaction() as con:
        audit=con.execute("select detail from startup_radar.admin_audit where action='CHANNEL_CONFIGURATION' and entity_id=%s order by created_at",(str(sid),)).fetchall()
        assert len(audit)==3 and all(row['detail']['reason']==config['note'] for row in audit)
        assert 'chat_id' not in str(audit)


@pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Explicit ephemeral database required')
def test_zero_subscribers_are_explicit_noop_without_transport(context):
    transport=Mock()
    for kind in ('DIGEST','HIGH_FIT','REMINDER'):
        assert plan_notifications(context['db'],kind)==0
        result=deliver_pending(context['db'],transport,kind)
        assert result['no_op'] and result['reason']=='NO_PENDING_DELIVERY' and result['delivered']==result['attempted_batches']==0
    transport.send.assert_not_called()


@pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Explicit ephemeral database required')
def test_channel_failure_blocks_prepared_work_and_preferences_cannot_clear_it(context):
    c=context
    with c['db'].transaction() as con:
        con.execute("insert into startup_radar.telegram_subscriptions(team_id,chat_id,channel_health) values(%s,'FIXTURE','HEALTHY')",(c['team']['id'],))
    refresh_recommendations(c['db'])
    assert plan_notifications(c['db'],'DIGEST')==plan_notifications(c['db'],'REMINDER')==1
    transport=Mock();transport.send.return_value={'state':'FAILED','error':'Forbidden','channel_health':'BLOCKED'}
    assert deliver_pending(c['db'],transport,'DIGEST')['failed']==1
    assert prefs(c,changes=ON)['subscriptions'][0]['channel_health']=='BLOCKED'
    assert deliver_pending(c['db'],transport,'REMINDER')['cancelled']==1
    assert plan_notifications(c['db'],'HIGH_FIT')==0
    transport.send.assert_called_once()
