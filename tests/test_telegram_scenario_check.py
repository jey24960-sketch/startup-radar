import os
from unittest.mock import Mock
import pytest
from test_database import db
from test_web_runtime import context
from test_program_responses_db import setup,answer
from tools.telegram_scenario_check import check,ApprovedMessages
from radar.models import TeamProfile,ProductStage,apply_preset,update_profile

pytestmark=pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Explicit ephemeral database required')


def test_three_reviewed_scenarios_use_real_planner_and_restore_preferences(context,monkeypatch,tmp_path):
    c=context;c['program'].product_stages=[ProductStage.IDEA]
    version=setup(c);answer(c,version,{'offline':True})
    profile=update_profile(apply_preset(TeamProfile(),0),{'preferred_program_types':['GRANT']})
    c['db'].save_profile(c['team']['id'],profile,c['admin'],1)
    with c['db'].transaction() as connection:
        connection.execute("update startup_radar.teams set name='운영 검증용 scenario fixture' where id=%s",(c['team']['id'],))
        connection.execute("update startup_radar.sources set adapter='KSTARTUP' where id=%s",(c['source'],))
        connection.execute("update startup_radar.runtime_settings set value=value || '{\"enabled\":false}'::jsonb where key='scheduling'")
        connection.execute('insert into startup_radar.team_notification_preferences(team_id,enabled,digest_enabled,alerts_enabled,reminders_enabled) values(%s,false,true,true,true)',(c['team']['id'],))
    monkeypatch.chdir(tmp_path)
    env={'GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_RUN_ATTEMPT':'1','GITHUB_RUN_ID':'fixture',
         'TELEGRAM_CHAT_ID':'-123','TELEGRAM_BOT_TOKEN':'fixture','SCENARIO_CHECK_MODE':'prepare',
         'SCENARIO_CHECK_TEAM_ID':str(c['team']['id']),'SCENARIO_CHECK_PROGRAM_ID':str(c['saved']['program_id']),
         'RADAR_MEMBER_NOTICE_URL':'https://preview.example/notice',
         'DATABASE_URL':'postgresql://postgres.etvffzxqdgblvkfdikwl:fixture@aws-1-ap-south-1.pooler.supabase.com:5432/postgres'}
    factory=Mock();factory.return_value.send.return_value={'state':'DELIVERED','receipt':{'message_id':901}}
    prepared=check(c['db'],env,factory)
    assert prepared['status']=='SUCCESS' and len(prepared['prepared'])==3,str(prepared)
    assert prepared['messages_sent']==0 and prepared['preferences_restored']
    factory.assert_not_called()
    delivered=check(c['db'],{**env,'SCENARIO_CHECK_MODE':'deliver'},factory)
    assert delivered['status']=='SUCCESS' and delivered['messages_sent']==3 and delivered['duplicate_sends']==0
    assert factory.return_value.send.call_count==3
    assert all(row['state']=='DELIVERED' and row['attempts']==1 for row in delivered['receipts'])
    assert '날짜 조건 재현' in factory.return_value.send.call_args.args[1]
    again=check(c['db'],{**env,'SCENARIO_CHECK_MODE':'deliver'},factory)
    assert again['status']=='FAILED' and factory.return_value.send.call_count==3
    with c['db'].transaction() as connection:
        assert connection.execute('select enabled from startup_radar.team_notification_preferences where team_id=%s',(c['team']['id'],)).fetchone()['enabled'] is False


def test_transport_rejects_other_targets_and_repeated_text():
    sender=Mock();wrapper=ApprovedMessages(sender,'approved',['reviewed'])
    with pytest.raises(ValueError):wrapper.send('other','reviewed')
    with pytest.raises(ValueError):wrapper.send('approved','unreviewed')
    wrapper.send('approved','reviewed')
    with pytest.raises(ValueError):wrapper.send('approved','reviewed')
    sender.send.assert_called_once_with('approved','reviewed')
