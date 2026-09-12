import os
from uuid import uuid4
import pytest,psycopg
from psycopg.types.json import Jsonb
from radar.recommendations import refresh_recommendations
from radar.notifications import plan_notifications,deliver_pending
from test_database import db
from test_web_runtime import context
from test_profile_commands import call

pytestmark=pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Explicit ephemeral database required')
ON={'enabled':True,'digest_enabled':True,'alerts_enabled':True,'reminders_enabled':True}
def prefs(c,user=None,changes=None):
 args=[c['team']['id']]
 if changes is not None:args.append(Jsonb(changes))
 return call(c['db'],user or c['admin'],'gfc_radar_save_preferences' if changes is not None else 'gfc_radar_preferences',*args)

def test_preferences_unconnected_connected_and_private_projection(context):
 c=context
 assert prefs(c)['connected'] is False and prefs(c)['preferences']==ON
 off={**ON,'enabled':False};assert prefs(c,changes=off)['preferences']==off
 with c['db'].transaction() as con:
  con.execute('insert into startup_radar.telegram_subscriptions(team_id,chat_id) values(%s,%s)',(c['team']['id'],'PRIVATE_CHAT_CANARY'))
 assert prefs(c)['connected'] is True and 'PRIVATE_CHAT_CANARY' not in str(prefs(c))
 assert prefs(c,changes=ON)['updated']==1
 with c['db'].transaction() as con:
  assert con.execute("select count(*) n from startup_radar.admin_audit where action='TEAM_NOTIFICATION_PREFERENCES' and entity_id=%s",(str(c['team']['id']),)).fetchone()['n']==2
 with pytest.raises(psycopg.errors.InsufficientPrivilege):prefs(c,user=c['other'])
 with c['db'].transaction() as con:con.execute("insert into startup_radar.team_members(team_id,user_id,role) values(%s,%s,'MEMBER')",(c['team']['id'],c['other']))
 assert prefs(c,user=c['other'])['connected'] is True
 with pytest.raises(psycopg.errors.InsufficientPrivilege):prefs(c,user=c['other'],changes=off)
 for invalid in ({'enabled':True},{**ON,'enabled':'true'},{**ON,'chat_id':'forged'},{**ON,'enabled':None}):
  with pytest.raises(psycopg.errors.InvalidParameterValue):prefs(c,changes=invalid)

def test_direct_preferences_are_rechecked_before_plan_and_delivery(context):
 c=context
 with c['db'].transaction() as con:con.execute('insert into startup_radar.telegram_subscriptions(team_id,chat_id) values(%s,%s)',(c['team']['id'],'FIXTURE'))
 refresh_recommendations(c['db']);assert plan_notifications(c['db'],'DIGEST')==1
 # A direct authorized RLS write need not mutate channel rows for the worker to
 # enforce it. No transport call is permitted after the stored preference changes.
 with c['db'].transaction(c['admin']) as con:con.execute('insert into startup_radar.team_notification_preferences(team_id,enabled) values(%s,false)',(c['team']['id'],))
 class NeverSend:
  def send(self,*args):raise AssertionError('Disabled preference reached transport')
 result=deliver_pending(c['db'],NeverSend(),'DIGEST');assert result['cancelled']==1 and result['delivered']==0
 assert plan_notifications(c['db'],'HIGH_FIT')==0

def test_health_requires_gfc_admin_and_redacts_raw_operational_data(context):
 c=context
 with c['db'].transaction() as con:
  con.execute("update startup_radar.sources set config='{"+'"api_key":"PRIVATE_CONFIG_CANARY"'+"}' where id=%s",(c['source'],))
  run=con.execute("insert into startup_radar.ingestion_runs(status,trigger_type,summary) values('FAILED','fixture',%s) returning id",(Jsonb({'new_programs':0,'eligibility_error':'PRIVATE_ERROR_CANARY','token':'PRIVATE_TOKEN_CANARY'}),)).fetchone()['id']
  con.execute("insert into startup_radar.source_run_results(run_id,source_id,status,failures,latency_ms) values(%s,%s,'FAILED',%s,25)",(run,c['source'],Jsonb([{'kind':'API_AUTH','message':'PRIVATE_ERROR_CANARY','url':'PRIVATE_URL_CANARY'}])))
  # GFC admin can monitor without a legacy Radar admin_users mapping.
  con.execute("insert into public.test_gfc_roles values(%s,'admin')",(c['other'],))
 health=call(c['db'],c['other'],'gfc_radar_health')
 assert health['enabled_sources']==1 and health['successful_sources']==0 and health['runs'][0]['status']=='FAILED'
 assert health['sources'][0]['failures']==[{'kind':'API_AUTH'}] and health['sources'][0]['latency_ms']==25
 assert health['calculation_queue']['pending']==2 and 'CANARY' not in str(health)
 with c['db'].transaction() as con:con.execute("update public.test_gfc_roles set role='member' where user_id=%s",(c['other'],))
 with pytest.raises(psycopg.errors.InsufficientPrivilege):call(c['db'],c['other'],'gfc_radar_health')
 with c['db'].transaction() as con:con.execute("update public.test_gfc_roles set role='external' where user_id=%s",(c['other'],))
 with pytest.raises(psycopg.errors.InsufficientPrivilege):call(c['db'],c['other'],'gfc_radar_health')
 with pytest.raises(psycopg.errors.InsufficientPrivilege):prefs(c,user=c['other'])

def test_anonymous_rpc_and_null_preferences_fail_closed(context):
 c=context
 with c['db'].transaction() as con:
  with pytest.raises(psycopg.errors.InsufficientPrivilege):
   with con.transaction():con.execute('set local role anon');con.execute('select public.gfc_radar_health()')
  with pytest.raises(psycopg.errors.InsufficientPrivilege):
   with con.transaction():con.execute('set local role anon');con.execute('select public.gfc_radar_preferences(%s)',(c['team']['id'],))
 with pytest.raises(psycopg.errors.InvalidParameterValue):call(c['db'],c['admin'],'gfc_radar_save_preferences',c['team']['id'],None)
