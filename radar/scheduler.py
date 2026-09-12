"""Seoul cadence with persistent claims. Failed or uncertain jobs require inspection."""
from uuid import UUID
from psycopg.types.json import Jsonb
from core.clock import now,SEOUL
from radar.ingestion import ingest
from radar.recommendations import refresh_recommendations
from radar.notifications import plan_notifications,deliver_pending


def due_tasks(settings,at):
    if at.tzinfo is None:raise ValueError('Timezone-aware scheduler timestamp required')
    at=at.astimezone(SEOUL)
    if not settings.get('enabled',True):return []
    tasks=[];day=at.date().isoformat()
    if settings.get('ingestion_enabled',True) and at.hour>=settings.get('ingestion_hour',6):tasks.append(('INGEST','INGEST:'+day))
    if at.weekday()==settings.get('digest_weekday',1) and at.hour>=settings.get('digest_hour',15):tasks.append(('DIGEST','DIGEST:'+at.strftime('%G-W%V')))
    if at.hour>=settings.get('reminder_hour',15):tasks.append(('REMINDER','REMINDER:'+day))
    return tasks


def execute(db,kind,source_slug=None,transport=None):
    if kind=='INGEST':
        sources=None
        if source_slug:
            with db.transaction() as c:sources=c.execute('select * from startup_radar.sources where slug=%s',(source_slug,)).fetchall()
            if not sources:raise ValueError('Unknown source slug')
        result=ingest(db,sources,trigger='v2-job')
        try:refresh_recommendations(db)
        except Exception as error:
            with db.transaction() as c:
                c.execute("update startup_radar.ingestion_runs set status='PARTIAL_SUCCESS',summary=summary || %s where id=%s",
                    (Jsonb({'eligibility_error':type(error).__name__}),result['id']))
            return {**result,'status':'PARTIAL_SUCCESS','eligibility_error':type(error).__name__}
        with db.transaction() as c:
            c.execute("delete from startup_radar.feed_snapshots where refreshed_at<now()-interval '7 days'")
        # Valid programs from successful sources survive partial source failure.
        if transport and result['status']!='FAILED':
            plan_notifications(db,'HIGH_FIT')
            alert=deliver_pending(db,transport,'HIGH_FIT');result['alerts']=alert
            if alert['status']!='SUCCESS':result['status']='PARTIAL_SUCCESS'
        return result
    if kind not in ('DIGEST','REMINDER','HIGH_FIT'):raise ValueError('Unsupported task kind')
    refresh_recommendations(db)
    if transport is None:return {'status':'SUCCESS','delivery':'DISABLED','message':'Recommendations refreshed; no notification ledger or external message created'}
    added=plan_notifications(db,kind)
    return {**deliver_pending(db,transport,kind),'planned':added}


def tick(db,at=None,transport=None,executor=execute):
    at=at or now()
    with db.transaction() as c:settings=c.execute("select value from startup_radar.runtime_settings where key='scheduling'").fetchone()['value']
    results=[]
    for kind,key in due_tasks(settings,at):
        with db.transaction() as c:
            claimed=c.execute("insert into startup_radar.schedule_claims(task_key,kind,state) values(%s,%s,'RUNNING') on conflict do nothing returning task_key",(key,kind)).fetchone()
        if not claimed:continue
        try:result=executor(db,kind,transport=transport)
        except Exception as error:result={'status':'FAILED','error':type(error).__name__}
        with db.transaction() as c:c.execute('update startup_radar.schedule_claims set state=%s,finished_at=now(),result=%s where task_key=%s',(result['status'],Jsonb(result),key))
        results.append({'key':key,**result})
    status='SUCCESS' if all(r['status']=='SUCCESS' for r in results) else 'PARTIAL_SUCCESS' if any(r['status']=='SUCCESS' for r in results) else 'FAILED'
    return {'status':status,'tasks':results}


def run_job(db,kind,source_slug=None,job_id=None,transport=None,executor=execute):
    # Hold one transaction-level lock across work; process exit releases it. The outbox
    # additionally uses per-batch locks/claims, so a crash never blindly resends.
    with db.transaction() as lock:
        if not lock.execute('select pg_try_advisory_xact_lock(782394202) acquired').fetchone()['acquired']:
            return {'status':'FAILED','error':'Another V2 job is running; request remains pending'}
        if job_id:
            job_id=UUID(str(job_id))
            with db.transaction() as c:
                job=c.execute("update startup_radar.job_requests set state='RUNNING' where id=%s and state in ('REQUESTED','UNCERTAIN') and kind=%s and source_slug is not distinct from %s returning id",
                              (job_id,kind,source_slug)).fetchone()
            if not job:return {'status':'SUCCESS','state':'DUPLICATE_OR_MISMATCHED_JOB','executed':False}
        try:result=tick(db,transport=transport,executor=executor) if kind=='TICK' else executor(db,kind,source_slug=source_slug,transport=transport)
        except Exception as error:result={'status':'FAILED','error':type(error).__name__}
        if job_id:
            with db.transaction() as c:c.execute('update startup_radar.job_requests set state=%s,result=%s,finished_at=now() where id=%s',(result['status'],Jsonb(result),job_id))
        return result
