"""Prepare/review then deliver one real digest to the existing approved target."""
import json,os,re,sys
from pathlib import Path
from uuid import UUID
from urllib.parse import urlsplit
from psycopg.types.json import Jsonb
from radar.database import Database
from radar.notifications import TelegramTransport,plan_notifications,deliver_pending
from radar.scheduler import run_job

FLAGS=('enabled','digest_enabled','alerts_enabled','reminders_enabled')
PREFIX='[운영 검증용 · 정식 알림 원장 확인]\n'


def validate_environment(env):
    if env.get('GITHUB_EVENT_NAME')!='workflow_dispatch' or env.get('GITHUB_RUN_ATTEMPT')!='1':
        raise ValueError('Only the first manual workflow attempt is allowed')
    if env.get('LEDGER_CHECK_MODE') not in ('prepare','deliver'):raise ValueError('Explicit prepare/deliver mode required')
    team=UUID(env.get('LEDGER_CHECK_TEAM_ID',''))
    target=env.get('TELEGRAM_CHAT_ID','').strip()
    if not re.fullmatch(r'-?\d+|@[A-Za-z0-9_]+',target) or not env.get('TELEGRAM_BOT_TOKEN'):
        raise ValueError('Existing single configured recipient and bot required')
    parsed=urlsplit(env.get('DATABASE_URL',''))
    if parsed.hostname!='aws-1-ap-south-1.pooler.supabase.com' or parsed.username!='postgres.etvffzxqdgblvkfdikwl' or parsed.port!=5432 or parsed.path!='/postgres':
        raise ValueError('Expected the existing shared project session pooler')
    if not env.get('RADAR_MEMBER_NOTICE_URL'):raise ValueError('Explicit reviewed member notice URL required')
    return team,target


class OneApprovedMessage:
    def __init__(self,transport,target,text):self.transport=transport;self.target=target;self.text=text;self.calls=0
    def send(self,target,text):
        if self.calls or target!=self.target or text!=self.text:raise ValueError('Unexpected extra message or target')
        self.calls+=1
        return self.transport.send(target,text)


def check(db,env,transport_factory=TelegramTransport):
    team_id,target=validate_environment(env);mode=env['LEDGER_CHECK_MODE']
    report={'kind':'DIGEST_LEDGER_CHECK','mode':mode,'team_id':str(team_id),'github_run_id':env.get('GITHUB_RUN_ID'),'messages_sent':0}
    def execute(database,kind,**kwargs):
        with database.transaction() as c:
            schedule=c.execute("select value from startup_radar.runtime_settings where key='scheduling'").fetchone()
            if not schedule or schedule['value'].get('enabled') is not False:raise ValueError('V2 automatic scheduling must remain disabled')
            team=c.execute('select name from startup_radar.teams where id=%s',(team_id,)).fetchone()
            pref=c.execute('select * from startup_radar.team_notification_preferences where team_id=%s',(team_id,)).fetchone()
            if not team or not team['name'].startswith('운영 검증용 ') or not pref or any(pref[f] for f in FLAGS):
                raise ValueError('Only an existing validation team with all notification flags off is allowed')
            subscriptions=c.execute('select * from startup_radar.telegram_subscriptions where team_id=%s',(team_id,)).fetchall()
            if len(subscriptions)>1 or any(s['chat_id']!=target or any(s[f] for f in FLAGS) for s in subscriptions):
                raise ValueError('Unexpected existing channel; inspection required')
            if not subscriptions:
                if mode!='prepare':raise ValueError('Prepare and review first')
                sub=c.execute('insert into startup_radar.telegram_subscriptions(team_id,chat_id,enabled,digest_enabled,alerts_enabled,reminders_enabled) values(%s,%s,false,false,false,false) returning id',(team_id,target)).fetchone()['id']
            else:sub=subscriptions[0]['id']
            batches=c.execute('select id,state,payload from startup_radar.notification_batches where subscription_id=%s',(sub,)).fetchall()
            if mode=='prepare' and batches:raise ValueError('Existing validation ledger; inspect instead of replanning')
            if mode=='deliver' and (len(batches)!=1 or batches[0]['state']!='PENDING' or not batches[0]['payload']['text'].startswith(PREFIX)):
                raise ValueError('Exactly one reviewed pending batch is required; delivered/uncertain batches cannot be resent')
        report['subscription_id']=str(sub)
        if env.get('GITHUB_ACTIONS')=='true':
            marker=Path('work/telegram-ledger-cleanup.json');marker.parent.mkdir(exist_ok=True)
            marker.write_text(json.dumps({'team_id':str(team_id),'subscription_id':str(sub),'github_run_id':env.get('GITHUB_RUN_ID')}),encoding='utf-8')
        try:
            with database.transaction() as c:
                c.execute('update startup_radar.team_notification_preferences set enabled=true,digest_enabled=true where team_id=%s',(team_id,))
                c.execute('update startup_radar.telegram_subscriptions set enabled=true,digest_enabled=true where id=%s',(sub,))
            if mode=='prepare':
                report['planned']=plan_notifications(database,'DIGEST',subscription_id=sub)
                report['second_plan_added']=plan_notifications(database,'DIGEST',subscription_id=sub)
                with database.transaction() as c:
                    batches=c.execute('select id,payload from startup_radar.notification_batches where subscription_id=%s and state=\'PENDING\'',(sub,)).fetchall()
                    if report['planned']!=1 or len(batches)!=1 or report['second_plan_added']!=0:
                        raise ValueError('Expected exactly one real notice and one batch; no send permitted')
                    payload={**batches[0]['payload'],'text':PREFIX+batches[0]['payload']['text']}
                    if len(payload['text'])>4096:raise ValueError('Review message too long')
                    c.execute('update startup_radar.notification_batches set payload=%s where id=%s',(Jsonb(payload),batches[0]['id']))
                    report.update(batch_id=str(batches[0]['id']),message_preview=payload['text'])
                report['state']='PREPARED_NOT_SENT'
            else:
                transport=OneApprovedMessage(transport_factory(env['TELEGRAM_BOT_TOKEN']),target,batches[0]['payload']['text'])
                report['delivery']=deliver_pending(database,transport,'DIGEST',limit=1,subscription_id=sub)
                report['transport_calls']=transport.calls
                report['messages_sent']=1 if report['delivery']['delivered']==1 else 0
                report['second_plan_added']=plan_notifications(database,'DIGEST',subscription_id=sub)
                report['second_delivery']=deliver_pending(database,transport,'DIGEST',limit=1,subscription_id=sub)
                with database.transaction() as c:
                    report['ledger']=c.execute('select b.id,b.state,b.attempts,b.receipt,b.delivered_at,(select count(*) from startup_radar.notification_items i where i.batch_id=b.id) item_count from startup_radar.notification_batches b where b.subscription_id=%s',(sub,)).fetchall()
                report['state']='DELIVERED' if report['messages_sent']==1 and report['second_plan_added']==0 and report['second_delivery']['delivered']==0 else 'DELIVERY_NOT_CONFIRMED'
            return {'status':'SUCCESS' if report['state'] in ('PREPARED_NOT_SENT','DELIVERED') else 'FAILED'}
        finally:
            with database.transaction() as c:
                c.execute('update startup_radar.telegram_subscriptions set enabled=false,digest_enabled=false,alerts_enabled=false,reminders_enabled=false where id=%s',(sub,))
                c.execute('update startup_radar.team_notification_preferences set enabled=false,digest_enabled=false,alerts_enabled=false,reminders_enabled=false where team_id=%s',(team_id,))
            report['notification_flags_restored_off']=True
    result=run_job(db,'DIGEST',executor=execute)
    return {**report,**result}


def cleanup(env):
    marker=Path('work/telegram-ledger-cleanup.json')
    if not marker.exists():return {'cleanup':'NOT_NEEDED'}
    team,target=validate_environment(env);saved=json.loads(marker.read_text(encoding='utf-8'))
    if saved['team_id']!=str(team) or saved['github_run_id']!=env.get('GITHUB_RUN_ID'):raise ValueError('Unexpected cleanup marker')
    with Database().transaction() as c:
        sub=c.execute('select s.id from startup_radar.telegram_subscriptions s join startup_radar.teams t on t.id=s.team_id where s.id=%s and s.team_id=%s and s.chat_id=%s and t.name like %s',
            (UUID(saved['subscription_id']),team,target,'운영 검증용 %')).fetchone()
        if not sub:raise ValueError('Cleanup scope no longer matches')
        c.execute('update startup_radar.telegram_subscriptions set enabled=false,digest_enabled=false,alerts_enabled=false,reminders_enabled=false where id=%s',(sub['id'],))
        c.execute('update startup_radar.team_notification_preferences set enabled=false,digest_enabled=false,alerts_enabled=false,reminders_enabled=false where team_id=%s',(team,))
    return {'cleanup':'FLAGS_OFF'}


def main():
    try:
        if '--cleanup' in sys.argv:
            print(json.dumps(cleanup(os.environ)));return 0
        validate_environment(os.environ)
        result=check(Database(),os.environ)
    except Exception as error:result={'status':'FAILED','state':'NOT_SENT_OR_INSPECT_LEDGER','error_class':type(error).__name__}
    path=Path('work/telegram-ledger-check.json');path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,default=str))
    return 0 if result.get('status')=='SUCCESS' else 1


if __name__=='__main__':raise SystemExit(main())
