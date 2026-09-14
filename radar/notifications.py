"""Persistent outbox with explicit delivery uncertainty and per-version keys."""
import html
import os
import re
from hashlib import sha256
from datetime import timedelta
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID
from psycopg.types.json import Jsonb
import requests
from core.clock import now, SEOUL
from radar.models import Program,TeamProfile
from radar.eligibility import evaluate
from radar.recommendations import configured_weights,rank
from radar.dates import days_left,program_status

FIELD_LABELS={'team_status':'팀 구성 상태','business_status':'사업자 상태','business_age_months':'사업 개월 수',
    'founder_age':'대표자 연령','region':'지역','student_status':'재학 여부','university_affiliation':'소속 대학',
    'team_size':'팀 인원','product_stage':'제품 단계','revenue':'매출액','has_revenue':'매출 발생 여부',
    'investment_received':'투자 유치 여부','industry':'업종','applicant_type':'신청자 유형',
    'registration_date':'사업자등록일','business_registration_date':'사업자등록일','prior_support_restrictions':'기존 지원 이력'}
STATE_LABELS={'IDEA':'아이디어','LANDING':'랜딩·프리토타입','MVP':'MVP','REVENUE':'초기 매출',
    'PRE_BUSINESS':'예비창업','SOLE_PROPRIETOR':'개인사업자','CORPORATION':'법인'}


def explain_fields(text):
    return re.sub(r'\b('+'|'.join(FIELD_LABELS)+r')\b',lambda match:FIELD_LABELS[match[0]],text)


class TelegramTransport:
    def __init__(self,token):self.token=token
    def send(self,chat_id,text):
        try:
            response=requests.post(f'https://api.telegram.org/bot{self.token}/sendMessage',
                json={'chat_id':chat_id,'text':text,'parse_mode':'HTML','disable_web_page_preview':True},timeout=20)
        except requests.RequestException:return {'state':'UNCERTAIN','error':'Telegram request outcome unknown'}
        try:payload=response.json()
        except ValueError:return {'state':'UNCERTAIN','error':'Telegram returned non-JSON response'}
        if not isinstance(payload,dict):return {'state':'UNCERTAIN','error':'Invalid Telegram response'}
        if response.status_code==200 and payload.get('ok') and isinstance(payload.get('result'),dict) and payload['result'].get('message_id'):
            return {'state':'DELIVERED','receipt':{'message_id':payload['result']['message_id']}}
        if payload.get('ok') is not False or response.status_code>=500:
            return {'state':'UNCERTAIN','error':'Telegram delivery could not be confirmed'}
        return {'state':'FAILED','error':f'Telegram rejected request (HTTP {response.status_code})',
                'channel_health':'BLOCKED' if response.status_code==403 else None}


def safe_link(url):
    try:
        parsed=urlsplit(url)
        return bool(parsed.scheme=='https' and parsed.hostname and not parsed.username and not parsed.password
                    and (parsed.port is None or 1<=parsed.port<=65535))
    except (ValueError,TypeError):return False


def message(program,team_name,outcome,score,explanation,kind,at=None,program_id=None):
    labels={'DIGEST':'StartupRadar Weekly','HIGH_FIT':'StartupRadar 중요 신규·변경 공고','REMINDER':'StartupRadar 마감 알림'}
    state='지원 가능' if outcome.status=='ELIGIBLE' else '추가 정보 필요'
    remaining=days_left(program,at)
    lines=[labels[kind],f'팀: {team_name}',program.title,program.organization,
           f'마감: D-{remaining}' if remaining is not None else '마감: 상시/원문 확인',
           f'지원 가능 여부: {state}',f'적합도: {score}',
           '혜택: '+(program.benefit_summary or program.support_summary or '원문 확인')[:600],
           '추천 이유: '+explain_fields(explanation)[:400]]
    if outcome.missing_profile_fields:lines.append('필요 정보: '+', '.join(FIELD_LABELS.get(field,'추가 프로필 정보') for field in outcome.missing_profile_fields))
    for question in outcome.missing_program_questions[:4]:
        lines.append('필요 확인: '+question.question)
    if len(outcome.missing_program_questions)>4:lines.append('추가 참여 조건은 GFC 공고 상세에서 확인하세요.')
    for rule in outcome.matched_requirements[:4]:
        quote=next((e.text for e in rule.evidence if e.verified),None)
        if quote:lines.append('확인 조건(원문): '+quote)
    text='\n'.join(html.escape(line[:700]) for line in lines)
    member_url=os.environ.get('RADAR_MEMBER_NOTICE_URL','https://www.gfc-startup.com/notice')
    parsed=urlsplit(member_url)
    if not safe_link(member_url) or parsed.query or parsed.fragment:
        raise ValueError('Member notice link must be an HTTPS URL without credentials')
    if program_id is not None:
        member_url=urlunsplit((parsed.scheme,parsed.netloc,parsed.path.rstrip('/')+'/radar/'+str(UUID(str(program_id))),'',''))
    for label,url in [('GFC에서 추천 보기',member_url),('원문 보기',program.official_url),('신청',program.application_url)]:
        if url and safe_link(url):text+=f'\n<a href="{html.escape(url,quote=True)}">{label}</a>'
    if len(text)>4000:raise ValueError('Notification exceeds safe size; cannot silently truncate conditions')
    return text


DEFAULT_POLICY={'digest_limit':5,'high_fit_daily_limit':2,'high_fit_min_days':3,'high_fit_new_days':7,'delivery_batch_limit':30}
FLAGS={'DIGEST':'digest_enabled','HIGH_FIT':'alerts_enabled','REMINDER':'reminders_enabled'}


def policy_for(c):
    row=c.execute("select value from startup_radar.runtime_settings where key='notification_policy'").fetchone()
    policy={**DEFAULT_POLICY,**(row['value'] if row else {})}
    if any(type(v) is not int or v<0 or v>365 for v in policy.values()):raise ValueError('Invalid notification policy')
    return policy


def plan_notifications(db,kind,at=None,*,subscription_id=None,program_id=None):
    at=at or now()
    if at.tzinfo is None:raise ValueError('Timezone-aware notification timestamp required')
    at=at.astimezone(SEOUL)
    if kind not in FLAGS:raise ValueError('Unknown notification kind')
    weights=configured_weights(db)
    added=0
    with db.transaction() as c:
        policy=policy_for(c)
        # Lock subscriptions in a stable order: parallel planners cannot exceed caps.
        subscriptions=c.execute('select s.*,startup_radar.channel_deliverable(s.enabled,s.channel_health,pref.enabled) enabled,(s.digest_enabled and coalesce(pref.digest_enabled,true)) digest_enabled,'
            '(s.alerts_enabled and coalesce(pref.alerts_enabled,true)) alerts_enabled,(s.reminders_enabled and coalesce(pref.reminders_enabled,true)) reminders_enabled,'
            't.name,p.profile,p.version profile_version from startup_radar.telegram_subscriptions s '
            'join startup_radar.teams t on t.id=s.team_id join startup_radar.team_profiles p on p.team_id=s.team_id '
            'left join startup_radar.team_notification_preferences pref on pref.team_id=s.team_id '
            'where startup_radar.channel_deliverable(s.enabled,s.channel_health,pref.enabled) and (%s::uuid is null or s.id=%s) order by s.id for update of s',
            (subscription_id,subscription_id)).fetchall()
        for sub in subscriptions:
            if not sub[FLAGS[kind]]:continue
            week=at.strftime('%G-W%V')
            if kind=='DIGEST':
                # One selected set per subscription per week, including failed deliveries.
                if c.execute("select 1 from startup_radar.notification_items where subscription_id=%s and kind='DIGEST' and payload->>'period'=%s limit 1",(sub['id'],week)).fetchone():continue
                capacity=policy['digest_limit']
            elif kind=='HIGH_FIT':
                midnight=at.replace(hour=0,minute=0,second=0,microsecond=0)
                count=c.execute("select count(*) n from startup_radar.notification_items where subscription_id=%s and kind='HIGH_FIT' and created_at>=%s and created_at<%s",
                                (sub['id'],midnight,midnight+timedelta(days=1))).fetchone()['n']
                capacity=max(0,policy['high_fit_daily_limit']-count)
            else:capacity=policy['delivery_batch_limit']
            rows=c.execute("select distinct on (v.program_id) r.*,v.program_id,v.id version_id,v.normalized,v.created_at version_created,coalesce(a.responses,'{}'::jsonb) responses "
                'from startup_radar.recommendations r join startup_radar.eligibility_evaluations e on e.id=r.evaluation_id '
                'join startup_radar.team_profile_versions tp on tp.id=e.profile_version_id '
                'join startup_radar.program_versions v on v.id=e.program_version_id join startup_radar.programs p on p.current_version_id=v.id '
                'left join startup_radar.team_program_responses a on a.team_id=r.team_id and a.program_version_id=v.id '
                'where r.team_id=%s and tp.version=%s and (%s::uuid is null or v.program_id=%s) order by v.program_id,r.created_at desc',
                (sub['team_id'],sub['profile_version'],program_id,program_id)).fetchall()
            current=[]
            for row in rows:
                program=Program.model_validate(row['normalized'])
                outcome=evaluate(TeamProfile.model_validate(sub['profile']),program.requirements,program.evidence_complete,at.date(),program_responses=row['responses'])
                ranking=rank(program,TeamProfile.model_validate(sub['profile']),outcome,weights=weights,at=at)
                if ranking and program_status(program,at)=='OPEN':
                    current.append(({**row,'score':ranking.score,'explanation':ranking.explanation},program,outcome))
            selected=[]
            for row,program,outcome in sorted(current,key=lambda item:item[0]['score'],reverse=True):
                if len(selected)>=capacity:break
                left=days_left(program,at)
                if kind=='HIGH_FIT':
                    if outcome.status!='ELIGIBLE' or row['score']<sub['high_fit_threshold'] or left is None or left<policy['high_fit_min_days']:continue
                    event=c.execute('select * from startup_radar.program_change_events where version_id=%s',(row['version_id'],)).fetchone()
                    if not event or not 0<=(at-event['created_at']).total_seconds()<=policy['high_fit_new_days']*86400:continue
                    period='material-version'
                elif kind=='REMINDER':
                    if left not in sub['reminder_days']:continue
                    period=f'D-{left}'
                else:period=week
                key=f"{kind}:{sub['id']}:{row['version_id']}:{period}"
                payload={'text':message(program,sub['name'],outcome,row['score'],row['explanation'],kind,at,program_id=row['program_id']),
                         'period':period,'profile_version':sub['profile_version'],'eligibility':outcome.status,'days_left':left,
                         'response_snapshot':row['responses'],'score':row['score']}
                item=c.execute("insert into startup_radar.notification_items(subscription_id,team_id,program_version_id,recommendation_id,dedupe_key,kind,state,payload,created_at) "
                    "values(%s,%s,%s,%s,%s,%s,'PENDING',%s,%s) on conflict(dedupe_key) do nothing returning *",
                    (sub['id'],sub['team_id'],row['version_id'],row['id'],key,kind,Jsonb(payload),at)).fetchone()
                if item:selected.append(item)
            if not selected:continue
            prefix=''
            if kind=='DIGEST':
                eligible=sum(i['payload']['eligibility']=='ELIGIBLE' for i in selected)
                closing=sum(i['payload']['days_left'] is not None and i['payload']['days_left']<=7 for i in selected)
                profile=sub['profile']
                prefix=html.escape(f"StartupRadar Weekly · {week}\n팀: {sub['name']}\n현재 상태: {STATE_LABELS.get(profile.get('product_stage'),'미입력')} / {STATE_LABELS.get(profile.get('business_status'),'미입력')}\n이번 주 선정: 지원 가능 {eligible} · 추가 정보 필요 {len(selected)-eligible} · D-7 이내 {closing}\n\n")
            # Every batch is one Telegram API message; item receipts map only to its contents.
            chunks=[];chunk=[];size=len(prefix)
            for item in selected:
                length=len(item['payload']['text'])+2
                if chunk and (kind!='DIGEST' or size+length>3900):chunks.append(chunk);chunk=[];size=0
                chunk.append(item);size+=length
            if chunk:chunks.append(chunk)
            for index,chunk in enumerate(chunks):
                text=(prefix if index==0 else '')+'\n\n'.join(i['payload']['text'] for i in chunk)
                if len(text)>4096:raise ValueError('Notification batch too long')
                key=sha256('|'.join(i['dedupe_key'] for i in chunk).encode()).hexdigest()
                batch=c.execute("insert into startup_radar.notification_batches(subscription_id,kind,dedupe_key,state,payload,created_at) values(%s,%s,%s,'PENDING',%s,%s) returning id",
                    (sub['id'],kind,key,Jsonb({'text':text,'profile_version':sub['profile_version']}),at)).fetchone()['id']
                c.execute('update startup_radar.notification_items set batch_id=%s where id=any(%s)',(batch,[i['id'] for i in chunk]))
            added+=len(selected)
    return added


def deliver_pending(db,transport,kind,limit=None,at=None,*,subscription_id=None):
    at=at or now()
    if at.tzinfo is None:raise ValueError('Timezone-aware notification timestamp required')
    at=at.astimezone(SEOUL)
    if kind not in FLAGS:raise ValueError('Unknown notification kind')
    weights=configured_weights(db)
    with db.transaction() as c:
        policy=policy_for(c)
        limit=policy['delivery_batch_limit'] if limit is None else limit
        run=c.execute("insert into startup_radar.notification_runs(kind,status) values(%s,'RUNNING') returning id",(kind,)).fetchone()['id']
    states=[];delivered_items=cancelled=0
    for _ in range(limit):
        with db.transaction() as c:
            batch=c.execute("select b.*,s.chat_id,startup_radar.channel_deliverable(s.enabled,s.channel_health,pref.enabled) enabled,(s.digest_enabled and coalesce(pref.digest_enabled,true)) digest_enabled,"
                "(s.alerts_enabled and coalesce(pref.alerts_enabled,true)) alerts_enabled,(s.reminders_enabled and coalesce(pref.reminders_enabled,true)) reminders_enabled,s.reminder_days,s.high_fit_threshold,"
                "p.profile,p.version profile_version from startup_radar.notification_batches b join startup_radar.telegram_subscriptions s on s.id=b.subscription_id "
                "join startup_radar.team_profiles p on p.team_id=s.team_id left join startup_radar.team_notification_preferences pref on pref.team_id=s.team_id "
                "where b.kind=%s and b.state='PENDING' and (%s::uuid is null or s.id=%s) order by b.created_at for update of b skip locked limit 1",
                (kind,subscription_id,subscription_id)).fetchone()
            if not batch:break
            items=c.execute("select i.*,v.normalized,p.current_version_id,r.score,coalesce(a.responses,'{}'::jsonb) responses from startup_radar.notification_items i "
                'join startup_radar.program_versions v on v.id=i.program_version_id join startup_radar.programs p on p.id=v.program_id '
                'join startup_radar.recommendations r on r.id=i.recommendation_id '
                'left join startup_radar.team_program_responses a on a.team_id=i.team_id and a.program_version_id=i.program_version_id '
                'where i.batch_id=%s',(batch['id'],)).fetchall()
            valid=bool(items) and batch['enabled'] and batch[FLAGS[kind]] and batch['payload']['profile_version']==batch['profile_version']
            for item in items:
                program=Program.model_validate(item['normalized']);left=days_left(program,at)
                profile=TeamProfile.model_validate(batch['profile'])
                outcome=evaluate(profile,program.requirements,program.evidence_complete,at.date(),program_responses=item['responses'])
                ranking=rank(program,profile,outcome,weights=weights,at=at)
                valid=valid and item['responses']==item['payload'].get('response_snapshot',{}) and ranking is not None
                if ranking:valid=valid and ranking.score==item['payload'].get('score',item['score'])
                valid=valid and item['program_version_id']==item['current_version_id'] and program_status(program,at)=='OPEN' and outcome.status==item['payload']['eligibility']
                if kind=='REMINDER':valid=valid and left in batch['reminder_days'] and item['payload']['period']==f'D-{left}'
                if kind=='DIGEST':valid=valid and item['payload']['period']==at.strftime('%G-W%V')
                if kind=='HIGH_FIT':valid=valid and outcome.status=='ELIGIBLE' and ranking is not None and ranking.score>=batch['high_fit_threshold'] and left is not None and left>=policy['high_fit_min_days'] and (at-batch['created_at']).total_seconds()<=86400
            if not valid:
                c.execute("update startup_radar.notification_batches set state='CANCELLED',error='Profile, program, subscription or deadline changed before delivery' where id=%s",(batch['id'],))
                c.execute("update startup_radar.notification_items set state='CANCELLED',error='Batch failed current-state revalidation' where batch_id=%s",(batch['id'],))
                cancelled+=len(items);continue
            c.execute("update startup_radar.notification_batches set state='SENDING',attempts=attempts+1,claimed_at=%s where id=%s",(at,batch['id']))
            c.execute("update startup_radar.notification_items set state='SENDING',attempts=attempts+1,run_id=%s where batch_id=%s",(run,batch['id']))
        try:
            result=transport.send(batch['chat_id'],batch['payload']['text'])
            if result.get('state') not in ('DELIVERED','FAILED','UNCERTAIN') or (result.get('state')=='DELIVERED' and not result.get('receipt')):
                result={'state':'UNCERTAIN','error':'Invalid transport receipt'}
        except Exception:result={'state':'UNCERTAIN','error':'Transport outcome unknown'}
        with db.transaction() as c:
            delivered_at=now() if result['state']=='DELIVERED' else None
            if result['state']=='DELIVERED' or result.get('channel_health')=='BLOCKED':
                c.execute('update startup_radar.telegram_subscriptions set channel_health=%s,health_checked_at=now(),health_reason=%s where id=%s',
                    ('HEALTHY' if delivered_at else 'BLOCKED','DELIVERY_RECEIPT' if delivered_at else 'TELEGRAM_FORBIDDEN',batch['subscription_id']))
            c.execute('update startup_radar.notification_batches set state=%s,receipt=%s,error=%s,delivered_at=%s where id=%s',
                (result['state'],Jsonb(result.get('receipt')),result.get('error'),delivered_at,batch['id']))
            c.execute('update startup_radar.notification_items set state=%s,delivery_receipts=%s,error=%s,delivered_at=%s where batch_id=%s',
                (result['state'],Jsonb([result['receipt']] if result.get('receipt') else []),result.get('error'),delivered_at,batch['id']))
        states.append(result['state'])
        if result['state']=='DELIVERED':delivered_items+=len(items)
    status='SUCCESS' if all(s=='DELIVERED' for s in states) else 'PARTIAL_SUCCESS' if 'DELIVERED' in states else 'FAILED'
    with db.transaction() as c:c.execute('update startup_radar.notification_runs set status=%s,finished_at=now() where id=%s',(status,run))
    return {'run_id':str(run),'status':status,'delivered':delivered_items,'failed':len(states)-states.count('DELIVERED'),'cancelled':cancelled,
            'attempted_batches':len(states),'no_op':not states and cancelled==0,
            'reason':'NO_PENDING_DELIVERY' if not states and cancelled==0 else None}


def recover_batch(db,batch_id,action,note,user_id):
    from radar.services import require_admin
    require_admin(db,user_id)
    if action not in ('RETRY_REJECTED','CONFIRM_NOT_SENT','CANCEL') or not 5<=len(note)<=500:raise ValueError('Recovery action and meaningful note required')
    with db.transaction() as c:
        batch=c.execute('select * from startup_radar.notification_batches where id=%s for update',(batch_id,)).fetchone()
        if not batch:raise LookupError('Batch not found')
        if batch['state'] in ('DELIVERED','CANCELLED','PENDING'):raise ValueError('Batch is not recoverable')
        if batch['state']=='SENDING' and (not batch['claimed_at'] or now()-batch['claimed_at']<timedelta(minutes=20)):
            raise ValueError('A recent in-flight send cannot be recovered')
        if action=='RETRY_REJECTED' and batch['state']!='FAILED':raise ValueError('Uncertain delivery requires explicit no-delivery confirmation')
        state='CANCELLED' if action=='CANCEL' else 'PENDING'
        c.execute('update startup_radar.notification_batches set state=%s,error=%s where id=%s',(state,note,batch_id))
        c.execute('update startup_radar.notification_items set state=%s,error=%s where batch_id=%s',(state,note,batch_id))
        c.execute('insert into startup_radar.admin_audit(actor_id,action,entity_id,detail) values(%s,%s,%s,%s)',
                  (user_id,'NOTIFICATION_'+action,str(batch_id),Jsonb({'previous_state':batch['state'],'note':note})))
    return {'state':state}
