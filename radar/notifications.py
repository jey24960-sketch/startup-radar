"""Persistent outbox with explicit delivery uncertainty and per-version keys."""
import html
from urllib.parse import urlsplit
from psycopg.types.json import Jsonb
import requests
from core.clock import now, SEOUL
from radar.models import Program,TeamProfile
from radar.eligibility import evaluate
from radar.dates import days_left,program_status


class TelegramTransport:
    def __init__(self,token):self.token=token
    def send(self,chat_id,text):
        try:
            response=requests.post(f'https://api.telegram.org/bot{self.token}/sendMessage',
                json={'chat_id':chat_id,'text':text,'parse_mode':'HTML','disable_web_page_preview':True},timeout=20)
        except requests.RequestException:return {'state':'UNCERTAIN','error':'Telegram request outcome unknown'}
        try:payload=response.json()
        except ValueError:return {'state':'UNCERTAIN','error':'Telegram returned non-JSON response'}
        if response.status_code==200 and payload.get('ok'):
            return {'state':'DELIVERED','receipt':{'message_id':payload['result']['message_id']}}
        return {'state':'FAILED','error':f'Telegram rejected request (HTTP {response.status_code})'}


def message(program,team_name,outcome,score,explanation,kind,at=None):
    labels={'DIGEST':'StartupRadar Weekly','HIGH_FIT':'StartupRadar 중요 신규·변경 공고','REMINDER':'StartupRadar 마감 알림'}
    state='지원 가능' if outcome.status=='ELIGIBLE' else '추가 정보 필요'
    remaining=days_left(program,at)
    lines=[labels[kind],f'팀: {team_name}',program.title,program.organization,
           f'마감: D-{remaining}' if remaining is not None else '마감: 상시/원문 확인',
           f'지원 가능 여부: {state}',f'적합도: {score}',
           '혜택: '+(program.benefit_summary or program.support_summary or '원문 확인')[:600],
           '추천 이유: '+explanation[:400]]
    if outcome.missing_profile_fields:lines.append('필요 정보: '+', '.join(outcome.missing_profile_fields))
    for rule in outcome.matched_requirements[:4]:
        lines.append(f'확인 조건: {rule.key} {rule.operator} {rule.value}')
    text='\n'.join(html.escape(line[:700]) for line in lines)
    for label,url in [('원문 보기',program.official_url),('신청',program.application_url)]:
        if url and urlsplit(url).scheme=='https':text+=f'\n<a href="{html.escape(url,quote=True)}">{label}</a>'
    if len(text)>4000:raise ValueError('Notification exceeds safe size; cannot silently truncate conditions')
    return text


def plan_notifications(db,kind,at=None):
    at=at or now()
    if at.tzinfo is None:raise ValueError('Timezone-aware notification timestamp required')
    at=at.astimezone(SEOUL)
    if kind not in ('DIGEST','HIGH_FIT','REMINDER'):raise ValueError('Unknown notification kind')
    added=0
    with db.transaction() as c:
        subscriptions=c.execute('select s.*,t.name,p.profile,p.version profile_version from radar.telegram_subscriptions s '
            'join radar.teams t on t.id=s.team_id join radar.team_profiles p on p.team_id=s.team_id where s.enabled=true').fetchall()
        for sub in subscriptions:
            setting={'DIGEST':'digest_enabled','HIGH_FIT':'alerts_enabled','REMINDER':'reminders_enabled'}[kind]
            if not sub[setting]:continue
            rows=c.execute('select distinct on (v.program_id) r.*,v.id version_id,v.normalized,v.created_at version_created,e.result '
                'from radar.recommendations r join radar.eligibility_evaluations e on e.id=r.evaluation_id '
                'join radar.team_profile_versions tp on tp.id=e.profile_version_id '
                'join radar.program_versions v on v.id=e.program_version_id join radar.programs p on p.current_version_id=v.id '
                'where r.team_id=%s and tp.version=%s order by v.program_id,r.created_at desc',(sub['team_id'],sub['profile_version'])).fetchall()
            rows=sorted(rows,key=lambda r:r['score'],reverse=True)
            selected_count=0
            for row in rows:
                if kind=='DIGEST' and selected_count>=5:break
                if kind=='HIGH_FIT' and selected_count>=2:break
                program=Program.model_validate(row['normalized'])
                outcome=evaluate(TeamProfile.model_validate(sub['profile']),program.requirements,program.evidence_complete,at.date())
                if outcome.status not in ('ELIGIBLE','NEEDS_INFO') or program_status(program,at)!='OPEN':continue
                left=days_left(program,at)
                if kind=='HIGH_FIT':
                    if outcome.status!='ELIGIBLE' or row['score']<sub['high_fit_threshold'] or left is None or left<3:continue
                    event=c.execute('select * from radar.program_change_events where version_id=%s',(row['version_id'],)).fetchone()
                    if not event or (at-event['created_at']).total_seconds()>7*86400:continue
                    period='material-version'
                elif kind=='REMINDER':
                    if left not in sub['reminder_days']:continue
                    period=f'D-{left}'
                else:period=at.strftime('%G-W%V')
                key=f"{kind}:{sub['id']}:{row['version_id']}:{period}"
                payload={'text':message(program,sub['name'],outcome,row['score'],row['explanation'],kind,at)}
                inserted=c.execute("insert into radar.notification_items(subscription_id,team_id,program_version_id,recommendation_id,dedupe_key,kind,state,payload) "
                    "values(%s,%s,%s,%s,%s,%s,'PENDING',%s) on conflict(dedupe_key) do nothing returning id",
                    (sub['id'],sub['team_id'],row['version_id'],row['id'],key,kind,Jsonb(payload))).fetchone()
                added+=bool(inserted)
                selected_count+=1
    return added


def deliver_pending(db,transport,kind,limit=30):
    with db.transaction() as c:
        run=c.execute("insert into radar.notification_runs(kind,status) values(%s,'RUNNING') returning id",(kind,)).fetchone()['id']
    states=[]
    for _ in range(limit):
        with db.transaction() as c:
            item=c.execute("select i.*,s.chat_id from radar.notification_items i join radar.telegram_subscriptions s on s.id=i.subscription_id "
                "where i.kind=%s and i.state='PENDING' and s.enabled=true order by i.created_at for update of i skip locked limit 1",(kind,)).fetchone()
            if not item:break
            c.execute("update radar.notification_items set state='SENDING',attempts=attempts+1,run_id=%s where id=%s",(run,item['id']))
        try:result=transport.send(item['chat_id'],item['payload']['text'])
        except Exception:result={'state':'UNCERTAIN','error':'Transport outcome unknown'}
        with db.transaction() as c:
            c.execute('update radar.notification_items set state=%s,delivery_receipts=%s,error=%s,delivered_at=%s where id=%s',
                (result['state'],Jsonb([result['receipt']] if result.get('receipt') else []),result.get('error'),
                 now() if result['state']=='DELIVERED' else None,item['id']))
        states.append(result['state'])
    status='SUCCESS' if all(s=='DELIVERED' for s in states) else 'PARTIAL_SUCCESS' if 'DELIVERED' in states else 'FAILED'
    with db.transaction() as c:c.execute('update radar.notification_runs set status=%s,finished_at=now() where id=%s',(status,run))
    return {'run_id':str(run),'status':status,'delivered':states.count('DELIVERED'),'failed':len(states)-states.count('DELIVERED')}
