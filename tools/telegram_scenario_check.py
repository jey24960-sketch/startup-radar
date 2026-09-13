"""Review then send three scoped checks; reminder clocks are explicitly simulated."""
import json,os,sys
from datetime import datetime,timedelta
from pathlib import Path
from uuid import UUID
from psycopg.types.json import Jsonb
from core.clock import now
from radar.database import Database
from radar.models import Program
from radar.notifications import TelegramTransport,plan_notifications,deliver_pending
from radar.recommendations import refresh_recommendations
from radar.scheduler import run_job
from tools.telegram_ledger_check import FLAGS,validate_environment,cleanup

SCENARIOS=('HIGH_FIT','D-7','D-3')
PREFIX='[운영 검증 · '


def environment(env):
    return {**env,'LEDGER_CHECK_MODE':env.get('SCENARIO_CHECK_MODE',''),
            'LEDGER_CHECK_TEAM_ID':env.get('SCENARIO_CHECK_TEAM_ID','')}


class ApprovedMessages:
    def __init__(self,transport,target,texts):
        self.transport=transport;self.target=target;self.texts=set(texts);self.sent=set()
    def send(self,target,text):
        if target!=self.target or text not in self.texts or text in self.sent:
            raise ValueError('Unexpected recipient or repeated message')
        self.sent.add(text)
        return self.transport.send(target,text)


def check(db,env,transport_factory=TelegramTransport):
    env=environment(env);team,target=validate_environment(env)
    program_id=UUID(env.get('SCENARIO_CHECK_PROGRAM_ID',''));mode=env['LEDGER_CHECK_MODE']
    report={'mode':mode,'team_id':str(team),'program_id':str(program_id),'messages_sent':0,
            'reminder_clock':'simulated; actual source deadlines remain unchanged'}
    def execute(database,kind,**kwargs):
        with database.transaction() as c:
            schedule=c.execute("select value from startup_radar.runtime_settings where key='scheduling'").fetchone()['value']
            assert schedule.get('enabled') is False,'Recurring scheduling must be disabled'
            team_row=c.execute('select name from startup_radar.teams where id=%s',(team,)).fetchone()
            pref=c.execute('select * from startup_radar.team_notification_preferences where team_id=%s',(team,)).fetchone()
            assert team_row and team_row['name'].startswith('운영 검증용 ') and pref and pref['enabled'] is False
            original={key:pref[key] for key in FLAGS}
            version=c.execute('select v.id,v.normalized from startup_radar.programs p join startup_radar.program_versions v on v.id=p.current_version_id where p.id=%s',(program_id,)).fetchone()
            assert version and c.execute("select 1 from startup_radar.program_sources ps join startup_radar.sources s on s.id=ps.source_id where ps.program_id=%s and s.adapter in ('KSTARTUP','BIZINFO')",(program_id,)).fetchone()
            program=Program.model_validate(version['normalized'])
            assert program.evidence_complete and program.application_end_at and program.application_end_at>now()
            subscriptions=c.execute('select * from startup_radar.telegram_subscriptions where team_id=%s',(team,)).fetchall()
            assert len(subscriptions)<=1 and all(s['chat_id']==target and not any(s[k] for k in FLAGS) for s in subscriptions)
            if subscriptions:sub=subscriptions[0]['id']
            else:
                assert mode=='prepare','Prepare first'
                sub=c.execute('insert into startup_radar.telegram_subscriptions(team_id,chat_id,enabled,digest_enabled,alerts_enabled,reminders_enabled) values(%s,%s,false,false,false,false) returning id',(team,target)).fetchone()['id']
            batches=c.execute('select * from startup_radar.notification_batches where subscription_id=%s',(sub,)).fetchall()
            if mode=='prepare':assert not batches,'Existing ledger must be inspected, not recreated'
            else:
                assert len(batches)==3 and all(b['state']=='PENDING' and b['payload'].get('validation_scenario') in SCENARIOS and b['payload']['text'].startswith(PREFIX) for b in batches),'Only three reviewed pending checks are allowed'
                assert {b['payload']['validation_scenario'] for b in batches}==set(SCENARIOS)
        marker=Path('work/telegram-ledger-cleanup.json');marker.parent.mkdir(exist_ok=True)
        marker.write_text(json.dumps({'team_id':str(team),'subscription_id':str(sub),'github_run_id':env.get('GITHUB_RUN_ID'),'original_preferences':original}),encoding='utf-8')
        report['subscription_id']=str(sub)
        try:
            refresh_recommendations(database,team_id=team)
            with database.transaction() as c:
                c.execute('update startup_radar.team_notification_preferences set enabled=true,digest_enabled=false,alerts_enabled=true,reminders_enabled=true where team_id=%s',(team,))
                c.execute('update startup_radar.telegram_subscriptions set enabled=true,digest_enabled=false,alerts_enabled=true,reminders_enabled=true where id=%s',(sub,))
            if mode=='prepare':
                prepared=[]
                for scenario in SCENARIOS:
                    kind='HIGH_FIT' if scenario=='HIGH_FIT' else 'REMINDER'
                    at=now() if scenario=='HIGH_FIT' else program.application_end_at-timedelta(days=int(scenario[2:]))
                    added=plan_notifications(database,kind,at,subscription_id=sub,program_id=program_id)
                    assert added==1 and plan_notifications(database,kind,at,subscription_id=sub,program_id=program_id)==0,'Expected one real program per scenario'
                    with database.transaction() as c:
                        rows=c.execute("select b.id,b.payload,i.program_version_id from startup_radar.notification_batches b join startup_radar.notification_items i on i.batch_id=b.id where b.subscription_id=%s and b.state='PENDING' and b.payload->>'validation_scenario' is null",(sub,)).fetchall()
                        assert len(rows)==1 and rows[0]['program_version_id']==version['id'],'Unexpected selected program; no send allowed'
                        row=rows[0]
                        label='고적합 공고 · 테스트 팀' if scenario=='HIGH_FIT' else scenario+' 날짜 조건 재현 · 실제 마감일 변경 없음'
                        payload={**row['payload'],'validation_scenario':scenario,'validation_at':at.isoformat(),'text':PREFIX+label+']\n'+row['payload']['text']}
                        assert len(payload['text'])<=4096
                        c.execute('update startup_radar.notification_batches set payload=%s where id=%s',(Jsonb(payload),row['id']))
                        prepared.append({'batch_id':str(row['id']),**payload})
                report['prepared']=prepared;report['state']='PREPARED_NOT_SENT'
            else:
                wrapper=ApprovedMessages(transport_factory(env['TELEGRAM_BOT_TOKEN']),target,[b['payload']['text'] for b in batches])
                results=[]
                for scenario in SCENARIOS:
                    batch=next(b for b in batches if b['payload']['validation_scenario']==scenario)
                    kind='HIGH_FIT' if scenario=='HIGH_FIT' else 'REMINDER'
                    at=now() if scenario=='HIGH_FIT' else datetime.fromisoformat(batch['payload']['validation_at'])
                    if scenario!='HIGH_FIT':assert at==program.application_end_at-timedelta(days=int(scenario[2:]))
                    result=deliver_pending(database,wrapper,kind,limit=1,at=at,subscription_id=sub)
                    results.append({'scenario':scenario,**result});report['delivery']=results
                    report['messages_sent']+=result['delivered']
                    if result['delivered']!=1:raise ValueError('Delivery not confirmed; inspect ledger, never automatically retry')
                    assert plan_notifications(database,kind,at,subscription_id=sub,program_id=program_id)==0
                for kind in ('HIGH_FIT','REMINDER'):
                    assert deliver_pending(database,wrapper,kind,limit=3,subscription_id=sub)['delivered']==0
                with database.transaction() as c:
                    report['receipts']=c.execute('select id,state,attempts,receipt,payload->>\'validation_scenario\' scenario from startup_radar.notification_batches where subscription_id=%s',(sub,)).fetchall()
                report['state']='DELIVERED';report['duplicate_sends']=0
            return {'status':'SUCCESS'}
        finally:
            with database.transaction() as c:
                c.execute('update startup_radar.telegram_subscriptions set enabled=false,digest_enabled=false,alerts_enabled=false,reminders_enabled=false where id=%s',(sub,))
                c.execute('update startup_radar.team_notification_preferences set enabled=%s,digest_enabled=%s,alerts_enabled=%s,reminders_enabled=%s where team_id=%s',(*[original[k] for k in FLAGS],team))
            report['preferences_restored']=True;report['subscription_disabled']=True
    result=run_job(db,'HIGH_FIT',executor=execute)
    return {**report,**result}


def main():
    if '--cleanup' in sys.argv:
        print(json.dumps(cleanup(environment(os.environ))));return 0
    try:result=check(Database(),os.environ)
    except Exception as error:result={'status':'FAILED','error_class':type(error).__name__,'message':'Inspect scoped ledger before retrying'}
    path=Path('work/telegram-scenario-check.json');path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,default=str))
    return 0 if result.get('status')=='SUCCESS' else 1


if __name__=='__main__':raise SystemExit(main())
