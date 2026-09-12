"""Telegram V2 command channel. All mutable state is in PostgreSQL."""
from uuid import UUID
import html
from psycopg.types.json import Jsonb
from radar.services import health,memberships,profile_for,require_admin
from radar.models import apply_preset,update_profile
from radar.recommendations import refresh_recommendations
from radar.jobs import dispatch_job


def handle_update(db,update,transport,dispatcher=dispatch_job):
    if not isinstance(update,dict):raise ValueError('Telegram update must be an object')
    update_id=update.get('update_id')
    if isinstance(update_id,bool) or not isinstance(update_id,int):raise ValueError('Invalid Telegram update_id')
    message=update.get('message') or {}
    if not isinstance(message,dict) or not isinstance(message.get('from'),dict) or not isinstance(message.get('chat'),dict):return {'state':'IGNORED'}
    if not isinstance(message.get('text'),str):return {'state':'IGNORED'}
    sender=str((message.get('from') or {}).get('id',''));chat_id=(message.get('chat') or {}).get('id')
    text=(message.get('text') or '').strip();parts=text.split();command=(parts[0].split('@')[0].lower() if parts else '')
    with db.transaction() as c:
        admin=c.execute('select * from radar.telegram_admins where telegram_user_id=%s',(sender,)).fetchone()
    if command!='/id' and not admin:return {'state':'IGNORED'}
    if command!='/id':require_admin(db,admin['user_id'])
    with db.transaction() as c:
        claimed=c.execute("insert into radar.telegram_updates(update_id,state) values(%s,'PROCESSING') on conflict do nothing returning update_id",(update_id,)).fetchone()
    if not claimed:return {'state':'DUPLICATE'}
    state='COMPLETED';result={}
    try:
        if command=='/id':reply=f'Telegram 사용자 ID: {sender}\n대화 ID: {chat_id}'
        elif command in ('/status','/health','/sources'):
            current=health(db,admin['user_id']);latest=current['runs'][0] if current['runs'] else None
            reply=f"등록 소스: {current['tracked_sources']} · 활성: {current['enabled_sources']} · 최근 성공: {current['successful_sources']}\n"
            reply+=f"최근 수집: {latest['status']} ({latest['started_at']})" if latest else '아직 수집 실행 기록이 없습니다.'
            schedule=next((s['value'] for s in current['settings'] if s['key']=='scheduling'),{})
            reply+=f"\n정기 자동화: {'켜짐' if schedule.get('enabled',True) else '중지'}"
            if command in ('/health','/sources'):
                reply+='\n'+'\n'.join(f"{s['name']}: {s['status'] or '미실행'}" for s in current['sources'][:30])
        elif command in ('/run','/digest'):
            result=dispatcher(db,'INGEST' if command=='/run' else 'DIGEST',user_id=admin['user_id'])
            reply=f"작업: {result['job_id']}\n상태: {result['state']}"
            if result.get('error'):reply+='\n'+result['error'];state='UNCERTAIN' if result['state']=='UNCERTAIN' else 'FAILED'
        elif command=='/team':
            own=memberships(db,admin['user_id'])['teams']
            if len(parts)==1:reply='팀 선택: /team UUID\n'+'\n'.join(f"{t['name']}: {t['id']}" for t in own)
            else:
                selected=UUID(parts[1])
                if not any(t['id']==selected for t in own):raise PermissionError('소속 팀만 선택할 수 있습니다.')
                with db.transaction() as c:c.execute('update radar.telegram_admins set selected_team_id=%s where telegram_user_id=%s',(selected,sender))
                reply='팀 선택을 저장했습니다.'
        elif command=='/stage':
            team_id=admin['selected_team_id']
            if not team_id:reply='먼저 /team 명령으로 팀을 선택하세요.'
            elif len(parts)!=2:reply='/stage 0..4 — 0 아이디어 전, 1 팀 구성·아이디어, 2 랜딩, 3 MVP, 4 사업자 보유'
            else:
                profile=profile_for(db,admin['user_id'],team_id)
                with db.transaction(admin['user_id']) as c:version=c.execute('select version from radar.team_profiles where team_id=%s',(team_id,)).fetchone()['version']
                if parts[1]=='초기매출':profile=update_profile(profile,{'product_stage':'REVENUE'})
                else:
                    aliases={'팀빌딩':0,'아이디어':1,'랜딩':2,'MVP':3}
                    preset=aliases[parts[1]] if parts[1] in aliases else int(parts[1])
                    profile=apply_preset(profile,preset)
                db.save_profile(team_id,profile,admin['user_id'],version)
                refresh_recommendations(db,team_id)
                reply='팀 프로필을 저장하고 지원 조건을 다시 평가했습니다.'
        elif command=='/stop':
            with db.transaction() as c:
                c.execute("update radar.runtime_settings set value=jsonb_set(value,'{enabled}','false'),updated_at=now() where key='scheduling'")
                c.execute('insert into radar.admin_audit(actor_id,action) values(%s,%s)',(admin['user_id'],'STOP_SCHEDULE'))
            reply='정기 수집·발송을 중지했습니다. 진행 중인 작업은 취소하지 않으며 /run 수동 실행은 가능합니다.'
        elif command=='/help':reply='/run 수집 실행\n/status 실제 상태\n/health 소스 건강도\n/team 팀 선택\n/stage 0..4 단계 설정\n/digest 주간 요약 요청\n/stop 정기 자동화 중지\n/id 내 ID'
        else:reply='알 수 없는 명령입니다. /help를 확인하세요.'
        receipt=transport.send(str(chat_id),html.escape(reply))
        if receipt['state']!='DELIVERED':state='UNCERTAIN';result['reply_error']=receipt.get('error')
    except Exception as error:
        state='FAILED';result={'error':type(error).__name__,'message':str(error)[:300]}
        # Do not dispatch again or leak credentials in an exception reply.
        try:transport.send(str(chat_id),'명령을 완료하지 못했습니다. 관리자 화면에서 작업 상태를 확인하세요.')
        except Exception:result['reply_error']='Error reply delivery unknown'
    with db.transaction() as c:c.execute('update radar.telegram_updates set state=%s,result=%s,updated_at=now() where update_id=%s',(state,Jsonb(result),update_id))
    return {'state':state}
