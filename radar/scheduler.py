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
        return all((failure.get('stage')=='DOCUMENT'
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
            from radar.quality import refresh_quality
            refresh_quality(db)
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


def tick(db,at=None,transport=None,executor=execute,execution_id=None):
    from radar.schedule_attempts import retry_policy,pending_retries,begin_attempt,finish_attempt
    fixed_at=at
    at=at or now()
    with db.transaction() as c:settings=c.execute("select value from startup_radar.runtime_settings where key='scheduling'").fetchone()['value']
    results=[]
    if settings.get('enabled',False):
        # A profile edit/new day is picked up without a Python HTTP request.
        # The existing repository and DB scheduling gates still apply.
        from radar.member_results import refresh_member_results
        refresh_member_results(db)
    policy=retry_policy(db)
    due=due_tasks(settings,at)
    if settings.get('enabled',False) and settings.get('ingestion_enabled',True):
        due+= [(r['kind'],r['task_key']) for r in pending_retries(db,at)]
    due=list(dict.fromkeys(due));observations=[]
    for kind,key in due:
        attempt,state=begin_attempt(db,kind,key,at,policy,execution_id)
        if not attempt:
            observations.append(state)
            continue
        # Retried acquisition never retries a possibly delivered external alert.
        delivery=transport if attempt['attempt_number']==1 else None
        try:result=executor(db,kind,transport=delivery)
        except Exception as error:result={'status':'FAILED','error':type(error).__name__}
        state=finish_attempt(db,attempt,result,policy,fixed_at or now())
        observations.append(state)
        results.append({'key':key,'attempt_id':str(attempt['id']),'attempt':attempt['attempt_number'],**result})
    states={s['state'] for s in observations}
    if 'UNCERTAIN' in states:status='UNCERTAIN'
    elif states.intersection({'FAILED_RETRYABLE','FAILED_TERMINAL'}):status='PARTIAL_SUCCESS' if 'SUCCESS' in states else 'FAILED'
    elif states-{'SUCCESS'}:status='PARTIAL_SUCCESS'
    else:status='SUCCESS'
    return {'status':status,'health_state':'NOT_DUE' if not due else status,'tasks':results,
            'due':[key for _,key in due],'task_states':observations,
            **{key:sum(bool(s[key]) for s in observations) for key in
               ('already_successful','unresolved_failure','retry_scheduled','terminal_failure','currently_running')}}


def run_job(db,kind,source_slug=None,job_id=None,transport=None,executor=execute):
    from radar.executions import claim_execution,finish_execution
    claim=claim_execution(db,kind,source_slug,job_id)  # {'status':'PAUSED'} while the operator pause is on
    if 'execution_id' not in claim:return claim
    execution_id=claim['execution_id']
    # BaseException/abrupt process termination deliberately leaves the claim.
    try:result=tick(db,transport=transport,executor=executor,execution_id=execution_id) if kind=='TICK' else executor(db,kind,source_slug=source_slug,transport=transport)
    except Exception as error:result={'status':'FAILED','error':type(error).__name__}
    try:finish_execution(db,execution_id,result)
    except Exception as error:
        return {'status':'UNCERTAIN','execution_id':execution_id,'error':type(error).__name__,
                'message':'Execution finalization uncertain; inspect durable owner and partial effects before retry'}
    return {**result,'execution_id':execution_id}
