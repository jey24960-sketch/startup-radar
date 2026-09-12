"""Authenticated lightweight dashboard API; production has no development auth bypass."""
import os
import hmac
import json
from pathlib import Path
from uuid import UUID
from typing import Literal
from fastapi import FastAPI,Depends,HTTPException,Query,Request
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field
from psycopg.types.json import Jsonb
from radar.auth import authenticated_user
from radar.database import Database
from radar.models import StrictModel,TeamProfile,PRESETS,apply_preset,update_profile
from radar.services import memberships,profile_for,browse,detail,health,require_admin,admin_trace
from radar.recommendations import refresh_recommendations
from radar.jobs import dispatch_job

ROOT=Path(__file__).resolve().parent.parent


class ProfilePatch(StrictModel):
    expected_version:int=Field(ge=1)
    changes:dict=Field(default_factory=dict)
    preset:int|None=Field(default=None,ge=0,le=4)
class TeamCreate(StrictModel):
    name:str=Field(min_length=1,max_length=100)
    owner_id:UUID
    preset:int=Field(default=0,ge=0,le=4)
class MemberAdd(StrictModel):
    user_id:UUID
    role:Literal['OWNER','EDITOR','MEMBER']='MEMBER'
class JobInput(StrictModel):
    kind:Literal['INGEST','DIGEST','REMINDER','HIGH_FIT']='INGEST'
    source_slug:str|None=Field(default=None,max_length=100)
class DuplicateDecision(StrictModel):
    state:Literal['CONFIRMED','REJECTED']
class Scheduling(StrictModel):
    enabled:bool=True
    ingestion_enabled:bool=True
    ingestion_hour:int=Field(default=6,ge=0,le=23)
    digest_weekday:int=Field(default=1,ge=0,le=6)
    digest_hour:int=Field(default=15,ge=0,le=23)
    reminder_hour:int=Field(default=15,ge=0,le=23)
    timezone:Literal['Asia/Seoul']='Asia/Seoul'
class SubscriptionInput(StrictModel):
    team_id:UUID
    chat_id:str=Field(min_length=1,max_length=100)
    enabled:bool=True
    digest_enabled:bool=True
    alerts_enabled:bool=True
    reminders_enabled:bool=True
    high_fit_threshold:float=Field(default=90,ge=0,le=100)
    reminder_days:list[int]=Field(default_factory=lambda:[7,3],max_length=10)
class NotificationRecovery(StrictModel):
    action:Literal['RETRY_REJECTED','CANCEL','CONFIRM_NOT_SENT']
    note:str=Field(min_length=5,max_length=500)


def create_app(database=None,preview=False):
    app=FastAPI(title='StartupRadar 2.0',docs_url=None,redoc_url=None)
    app.state.database=database
    def db():
        if app.state.database is None:
            try:app.state.database=Database()
            except ValueError as error:raise HTTPException(503,str(error))
        return app.state.database
    @app.middleware('http')
    async def security_headers(request,call_next):
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='same-origin'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self' https://*.supabase.co; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"
        if request.url.path.startswith('/api/'):response.headers['Cache-Control']='no-store'
        return response
    @app.exception_handler(PermissionError)
    async def forbidden(request,error):return JSONResponse({'detail':str(error)},status_code=403)
    @app.exception_handler(LookupError)
    async def not_found(request,error):return JSONResponse({'detail':str(error)},status_code=404)
    @app.exception_handler(ValueError)
    async def invalid(request,error):return JSONResponse({'detail':str(error)},status_code=400)
    @app.get('/')
    def index():return FileResponse(ROOT/'web/static/index.html')
    @app.get('/static/app.js',include_in_schema=False)
    def javascript():return FileResponse(ROOT/'web/static/app.js',media_type='text/javascript')
    @app.get('/api/public-config')
    def public_config():return {'supabase_url':os.environ.get('SUPABASE_URL'),'publishable_key':os.environ.get('SUPABASE_PUBLISHABLE_KEY'),
                                'presets':[{'id':i,'label':p[0]} for i,p in enumerate(PRESETS)],'preview':preview}
    @app.get('/api/me')
    def me(user=Depends(authenticated_user)):return memberships(db(),user)
    @app.get('/api/programs')
    def programs(team_id:UUID|None=None,preset:int|None=Query(default=None,ge=0,le=4),q:str=Query(default='',max_length=200),
                 program_type:str|None=None,status:str|None=None,eligibility:str|None=None,history:bool=False,recommended:bool=False,
                 limit:int=Query(default=30,ge=1,le=100),offset:int=Query(default=0,ge=0),user=Depends(authenticated_user)):
        return browse(db(),user,team_id,preset,q,program_type,status,eligibility,history,recommended,limit,offset)
    @app.get('/api/programs/{program_id}')
    def program_detail(program_id:UUID,team_id:UUID|None=None,preset:int|None=Query(default=None,ge=0,le=4),version_id:UUID|None=None,user=Depends(authenticated_user)):
        return detail(db(),user,program_id,team_id,preset,version_id)
    @app.get('/api/teams/{team_id}/profile')
    def team_profile(team_id:UUID,user=Depends(authenticated_user)):
        own=memberships(db(),user)
        row=next((t for t in own['teams'] if t['id']==team_id),None)
        if not row:raise PermissionError('Team is not accessible')
        return row
    @app.patch('/api/teams/{team_id}/profile')
    def patch_profile(team_id:UUID,body:ProfilePatch,user=Depends(authenticated_user)):
        profile=profile_for(db(),user,team_id)
        if body.preset is not None:profile=apply_preset(profile,body.preset)
        profile=update_profile(profile,body.changes)
        result=db().save_profile(team_id,profile,user,body.expected_version)
        refresh_recommendations(db(),team_id)
        return result
    @app.get('/api/teams/{team_id}/history')
    def team_history(team_id:UUID,user=Depends(authenticated_user)):
        profile_for(db(),user,team_id)
        # Explicitly project only this team's history, never Telegram IDs/payloads.
        with db().transaction() as c:
            rows=c.execute('select i.kind,i.state,i.delivered_at,i.created_at,v.program_id,p.title from radar.notification_items i '
                'join radar.program_versions v on v.id=i.program_version_id join radar.programs p on p.id=v.program_id '
                'where i.team_id=%s order by i.created_at desc limit 100',(team_id,)).fetchall()
        return {'items':rows}
    @app.get('/api/admin/health')
    def admin_health(user=Depends(authenticated_user)):return health(db(),user)
    @app.get('/api/admin/failures')
    def failures(user=Depends(authenticated_user)):
        require_admin(db(),user)
        with db().transaction() as c:
            documents=c.execute("select d.*,p.title from radar.documents d join radar.program_versions v on v.id=d.program_version_id join radar.programs p on p.id=v.program_id where extraction_status<>'SUCCESS' order by fetched_at desc nulls first limit 100").fetchall()
            sources=c.execute("select r.*,s.name,s.slug from radar.source_run_results r join radar.sources s on s.id=r.source_id where r.status<>'SUCCESS' order by r.created_at desc limit 100").fetchall()
        return {'documents':documents,'sources':sources}
    @app.get('/api/admin/duplicates')
    def duplicates(user=Depends(authenticated_user)):
        require_admin(db(),user)
        with db().transaction() as c:return {'items':c.execute('select d.*,p.title,q.title candidate_title from radar.possible_duplicates d join radar.programs p on p.id=d.program_id join radar.programs q on q.id=d.candidate_program_id order by d.created_at desc limit 100').fetchall()}
    @app.patch('/api/admin/duplicates/{duplicate_id}')
    def review_duplicate(duplicate_id:UUID,body:DuplicateDecision,user=Depends(authenticated_user)):
        require_admin(db(),user)
        with db().transaction() as c:
            row=c.execute('update radar.possible_duplicates set state=%s where id=%s returning *',(body.state,duplicate_id)).fetchone()
            if not row:raise LookupError('Duplicate relationship not found')
            c.execute('insert into radar.admin_audit(actor_id,action,entity_id,detail) values(%s,%s,%s,%s)',(user,'REVIEW_DUPLICATE',str(duplicate_id),Jsonb(body.model_dump())))
        return row
    @app.post('/api/admin/jobs',status_code=202)
    def trigger_job(body:JobInput,user=Depends(authenticated_user)):
        require_admin(db(),user)
        return dispatch_job(db(),body.kind,body.source_slug,user)
    @app.put('/api/admin/scheduling')
    def scheduling(body:Scheduling,user=Depends(authenticated_user)):
        require_admin(db(),user)
        with db().transaction() as c:
            c.execute("update radar.runtime_settings set value=%s,updated_at=now() where key='scheduling'",(Jsonb(body.model_dump()),))
            c.execute('insert into radar.admin_audit(actor_id,action,detail) values(%s,%s,%s)',(user,'UPDATE_SCHEDULING',Jsonb(body.model_dump())))
        return body
    @app.get('/api/admin/teams')
    def all_teams(user=Depends(authenticated_user)):
        require_admin(db(),user)
        with db().transaction() as c:return {'items':c.execute('select t.*,p.profile,p.version from radar.teams t join radar.team_profiles p on p.team_id=t.id order by t.created_at').fetchall()}
    @app.post('/api/admin/teams',status_code=201)
    def new_team(body:TeamCreate,user=Depends(authenticated_user)):
        require_admin(db(),user)
        return db().create_team(body.name,body.owner_id,apply_preset(TeamProfile(),body.preset))
    @app.post('/api/admin/teams/{team_id}/members',status_code=201)
    def add_member(team_id:UUID,body:MemberAdd,user=Depends(authenticated_user)):
        require_admin(db(),user)
        with db().transaction() as c:
            c.execute('insert into radar.team_members(team_id,user_id,role) values(%s,%s,%s) on conflict(team_id,user_id) do update set role=excluded.role',(team_id,body.user_id,body.role))
            c.execute('insert into radar.admin_audit(actor_id,action,entity_id,detail) values(%s,%s,%s,%s)',(user,'ADD_MEMBERSHIP',str(team_id),Jsonb(body.model_dump(mode='json'))))
        return {'state':'SAVED'}
    @app.get('/api/admin/notifications')
    def notifications(user=Depends(authenticated_user)):
        require_admin(db(),user)
        with db().transaction() as c:
            batches=c.execute('select b.*,s.team_id,t.name team_name from radar.notification_batches b join radar.telegram_subscriptions s on s.id=b.subscription_id join radar.teams t on t.id=s.team_id order by b.created_at desc limit 100').fetchall()
            items=c.execute('select i.id,i.state,i.kind,i.team_id,i.recommendation_id,i.program_version_id,i.delivered_at from radar.notification_items i order by i.created_at desc limit 100').fetchall()
        return {'batches':batches,'items':items}
    @app.post('/api/admin/notifications/{batch_id}/recover')
    def recover_notification(batch_id:UUID,body:NotificationRecovery,user=Depends(authenticated_user)):
        require_admin(db(),user)
        from radar.notifications import recover_batch
        return recover_batch(db(),batch_id,body.action,body.note,user)
    @app.put('/api/admin/subscriptions')
    def save_subscription(body:SubscriptionInput,user=Depends(authenticated_user)):
        require_admin(db(),user)
        if any(day<0 or day>365 for day in body.reminder_days):raise ValueError('Reminder days must be 0..365')
        with db().transaction() as c:
            return c.execute('insert into radar.telegram_subscriptions(team_id,chat_id,enabled,digest_enabled,alerts_enabled,reminders_enabled,high_fit_threshold,reminder_days) '
                'values(%s,%s,%s,%s,%s,%s,%s,%s) on conflict(team_id,chat_id) do update set enabled=excluded.enabled,digest_enabled=excluded.digest_enabled,alerts_enabled=excluded.alerts_enabled,reminders_enabled=excluded.reminders_enabled,high_fit_threshold=excluded.high_fit_threshold,reminder_days=excluded.reminder_days returning id',
                (body.team_id,body.chat_id,body.enabled,body.digest_enabled,body.alerts_enabled,body.reminders_enabled,body.high_fit_threshold,body.reminder_days)).fetchone()
    @app.get('/api/admin/trace/{recommendation_id}')
    def trace(recommendation_id:UUID,user=Depends(authenticated_user)):return admin_trace(db(),user,recommendation_id)
    @app.post('/telegram/webhook')
    async def webhook(request:Request):
        expected=os.environ.get('TELEGRAM_WEBHOOK_SECRET')
        if not expected:raise HTTPException(503,'Webhook is not configured')
        supplied=request.headers.get('X-Telegram-Bot-Api-Secret-Token','')
        if not hmac.compare_digest(supplied,expected):raise HTTPException(403,'Forbidden')
        raw=await request.body()
        if len(raw)>1_000_000:raise HTTPException(413,'Update too large')
        try:update=json.loads(raw)
        except ValueError:raise HTTPException(400,'Invalid JSON')
        if not isinstance(update,dict):raise HTTPException(400,'Expected Telegram update object')
        from radar.telegram import handle_update
        from radar.notifications import TelegramTransport
        from starlette.concurrency import run_in_threadpool
        token=os.environ.get('TELEGRAM_BOT_TOKEN')
        if not token:raise HTTPException(503,'Telegram transport is not configured')
        return await run_in_threadpool(handle_update,db(),update,TelegramTransport(token))
    app.mount('/static',StaticFiles(directory=ROOT/'web/static'),name='static')
    return app

app=create_app()
