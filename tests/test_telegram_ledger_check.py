from uuid import uuid4
from datetime import timedelta
from unittest.mock import Mock
import os,pytest
from test_database import db,program,source
from radar.models import TeamProfile
from radar.recommendations import refresh_recommendations
from core.clock import now
from tools.telegram_ledger_check import validate_environment,check


def env(team=None,mode='prepare'):
    return dict(GITHUB_EVENT_NAME='workflow_dispatch',GITHUB_RUN_ATTEMPT='1',GITHUB_RUN_ID='fixture',
        TELEGRAM_CHAT_ID='-123',TELEGRAM_BOT_TOKEN='fixture',LEDGER_CHECK_MODE=mode,
        LEDGER_CHECK_TEAM_ID=str(team or uuid4()),RADAR_MEMBER_NOTICE_URL='https://preview.example/notice',
        DATABASE_URL='postgresql://postgres.etvffzxqdgblvkfdikwl:fixture@aws-1-ap-south-1.pooler.supabase.com:5432/postgres')


@pytest.mark.parametrize('change',[{'GITHUB_RUN_ATTEMPT':'2'},{'GITHUB_EVENT_NAME':'push'},
    {'TELEGRAM_CHAT_ID':'123,456'},{'DATABASE_URL':'postgresql://localhost/other'},
    {'LEDGER_CHECK_MODE':'all'},{'RADAR_MEMBER_NOTICE_URL':''}])
def test_manual_single_target_context_is_required(change):
    with pytest.raises(ValueError):validate_environment({**env(),**change})


@pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Explicit ephemeral database required')
@pytest.mark.parametrize('delivery_state',['DELIVERED','FAILED','UNCERTAIN'])
def test_real_ledger_prepare_deliver_restoration_and_no_repeat(db,delivery_state,monkeypatch):
    owner=uuid4()
    with db.transaction() as c:c.execute('insert into auth.users values(%s)',(owner,))
    team=db.create_team('운영 검증용 fixture',owner,TeamProfile())
    with db.transaction() as c:
        c.execute("update startup_radar.runtime_settings set value=value || '{\"enabled\":false}'::jsonb where key='scheduling'")
        c.execute('insert into startup_radar.team_notification_preferences(team_id,enabled,digest_enabled,alerts_enabled,reminders_enabled) values(%s,false,true,true,true)',(team['id'],))
    p=program();p.program_types=['EDUCATION'];p.evidence_complete=True;p.application_end_at=now()+timedelta(days=14)
    db.save_program(p,source(db),'ledger-fixture',p.official_url,{},'fixture')
    refresh_recommendations(db)
    monkeypatch.setenv('RADAR_MEMBER_NOTICE_URL','https://preview.example/notice')
    factory=Mock();factory.return_value.send.return_value={'state':delivery_state,'receipt':{'message_id':88}} if delivery_state=='DELIVERED' else {'state':delivery_state,'error':'fixture'}
    prepared=check(db,env(team['id']),factory)
    assert prepared['state']=='PREPARED_NOT_SENT' and prepared['second_plan_added']==0
    assert 'https://preview.example/notice' in prepared['message_preview']
    factory.assert_not_called()
    delivered=check(db,env(team['id'],'deliver'),factory)
    assert delivered['transport_calls']==1 and delivered['second_delivery']['delivered']==0
    assert delivered['ledger'][0]['state']==delivery_state and delivered['ledger'][0]['attempts']==1
    assert delivered['subscription_disabled'] is True
    assert delivered['original_preferences_restored']==dict(enabled=False,digest_enabled=True,alerts_enabled=True,reminders_enabled=True)
    again=check(db,env(team['id'],'deliver'),factory)
    assert again['status']=='FAILED'
    factory.return_value.send.assert_called_once()
    with db.transaction() as c:
        assert c.execute('select enabled or digest_enabled or alerts_enabled or reminders_enabled active from startup_radar.telegram_subscriptions where team_id=%s',(team['id'],)).fetchone()['active'] is False
        assert c.execute('select enabled,digest_enabled,alerts_enabled,reminders_enabled from startup_radar.team_notification_preferences where team_id=%s',(team['id'],)).fetchone()==delivered['original_preferences_restored']
