"""Seoul cadence with persistent claims. Failed or uncertain jobs require inspection."""
from psycopg.types.json import Jsonb
from core.clock import now,SEOUL
from radar.ingestion import ingest
from radar.recommendations import refresh_recommendations
from radar.notifications import plan_notifications,deliver_pending


def ingestion_execution_result(result):
    """A completed safe import may retain incomplete source/evidence health.

    Never convert retrieval, persistence, changed-review, or empty-source failures
    into success. The persisted ingestion/source status is deliberately unchanged.
    """
    if result.get('status')!='PARTIAL_SUCCESS' or result.get('alerts',{}).get('status','SUCCESS')!='SUCCESS':return result
    sources=result.get('sources') or []
    evidence_warnings={'AI_DATE_SCHEMA','AI_DATE_EVIDENCE','AI_DATE_TIME_REQUIRED','AI_INPUT_LIMIT',
        'AI_TRUNCATED','AI_SCHEMA','AI_DATE_CONFLICT','AI_NORMALIZATION','DETAIL_UNAVAILABLE'}
    def completed(source):
        if not (source.get('discovered',0)>0 and source.get('fetched')==source['discovered']==source.get('parsed')):return False
        return all((failure.get('kind')=='PAGE_LIMIT' or failure.get('stage')=='DOCUMENT'
                    or failure.get('stage')=='EXTRACTION' and failure.get('kind') in evidence_warnings)
                   and failure.get('kind')!='SOURCE_REVIEW_CHANGED' for failure in source.get('failures',[]))
    if not sources or not all(completed(source) for source in sources):return result
    return {**result,'status':'SUCCESS','ingestion_status':'PARTIAL_SUCCESS',
            'completed_with_warnings':True,
            'message':'All discovered records persisted; source/evidence warnings remain visible and uncertain programs remain gated'}


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
    from radar.member_results import refresh_member_results
    if kind=='REFRESH':
        # Deterministic stored-page refresh; no ingestion, AI or delivery.
        return refresh_member_results(db)
    if kind=='INGEST':
        sources=None
        if source_slug:
            with db.transaction() as c:sources=c.execute('select * from startup_radar.sources where slug=%s',(source_slug,)).fetchall()
            if not sources:raise ValueError('Unknown source slug')
        result=ingest(db,sources,trigger='v2-job')
        try:
            refresh_recommendations(db)
            refresh_member_results(db)
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
        return ingestion_execution_result(result)
    if kind not in ('DIGEST','REMINDER','HIGH_FIT'):raise ValueError('Unsupported task kind')
    refresh_recommendations(db)
    refresh_member_results(db)
    if transport is None:return {'status':'SUCCESS','delivery':'DISABLED','message':'Recommendations refreshed; no notification ledger or external message created'}
    added=plan_notifications(db,kind)
    return {**deliver_pending(db,transport,kind),'planned':added}


def tick(db,at=None,transport=None,executor=execute):
    at=at or now()
    with db.transaction() as c:settings=c.execute("select value from startup_radar.runtime_settings where key='scheduling'").fetchone()['value']
    results=[]
    if settings.get('enabled',False):
        # A profile edit/new day is picked up without a Python HTTP request.
        # The existing repository and DB scheduling gates still apply.
        from radar.member_results import refresh_member_results
        refresh_member_results(db)
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
    from radar.executions import claim_execution,finish_execution
    claim=claim_execution(db,kind,source_slug,job_id)
    if 'execution_id' not in claim:return claim
    execution_id=claim['execution_id']
    # BaseException/abrupt process termination deliberately leaves the claim.
    try:result=tick(db,transport=transport,executor=executor) if kind=='TICK' else executor(db,kind,source_slug=source_slug,transport=transport)
    except Exception as error:result={'status':'FAILED','error':type(error).__name__}
    try:finish_execution(db,execution_id,result)
    except Exception as error:
        return {'status':'UNCERTAIN','execution_id':execution_id,'error':type(error).__name__,
                'message':'Execution finalization uncertain; inspect durable owner and partial effects before retry'}
    return {**result,'execution_id':execution_id}
