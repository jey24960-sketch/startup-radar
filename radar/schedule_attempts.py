"""Short claim transactions and immutable, bounded ingestion attempt history."""
from datetime import timedelta
from psycopg.types.json import Jsonb
from core.clock import now

RETRY_REASONS={'DNS_ERROR','NETWORK_ERROR','CONNECT_TIMEOUT','READ_TIMEOUT','HTTP_5XX','ROBOTS_FETCH_TIMEOUT'}
DEFAULT_POLICY={'max_attempts':3,'backoff_seconds':[900,3600],'max_age_hours':24}


def retry_policy(db):
    with db.transaction() as c:
        row=c.execute("select value from startup_radar.runtime_settings where key='ingestion_retry_policy'").fetchone()
    policy={**DEFAULT_POLICY,**(row['value'] if row else {})}
    maximum=policy['max_attempts'];backoff=policy['backoff_seconds'];age=policy['max_age_hours']
    if (type(maximum) is not int or not 1<=maximum<=5 or type(age) is not int or not 1<=age<=48
            or not isinstance(backoff,list) or len(backoff)<maximum-1
            or any(type(n) is not int or not 60<=n<=86400 for n in backoff)):
        raise ValueError('Invalid ingestion retry policy')
    return policy


def retryable_ingestion(result):
    if result.get('status') not in ('FAILED','PARTIAL_SUCCESS'):return False
    if result.get('alerts',{}).get('status','SUCCESS')!='SUCCESS' or result.get('eligibility_error'):return False
    sources=result.get('sources') or []
    if not sources:return False
    failures=[]
    for source in sources:
        errors=source.get('failures') or []
        if source.get('status')!='SUCCESS' and not errors:return False
        failures.extend(errors)
    if not failures:return False
    for error in failures:
        if error.get('retryable') is not True or error.get('stage')=='EXTRACTION':return False
        reason=error.get('reason_code')
        if reason=='ROBOTS_HTTP_ERROR':
            if error.get('cause_kind')!='HTTP_5XX' or not 500<=error.get('http_status',0)<=599:return False
        elif reason=='HTTP_5XX':
            if not 500<=error.get('http_status',0)<=599:return False
        elif reason not in RETRY_REASONS:return False
    return True


def classify_result(kind,result,number,policy,started_at,at):
    status=result.get('status')
    if status=='SUCCESS':return 'SUCCESS',None,None
    if status=='UNCERTAIN':return 'UNCERTAIN','EXTERNAL_OUTCOME_UNCERTAIN',None
    if kind=='INGEST' and retryable_ingestion(result):
        if number>=policy['max_attempts']:return 'FAILED_TERMINAL','RETRY_EXHAUSTED',None
        next_at=at+timedelta(seconds=policy['backoff_seconds'][min(number-1,len(policy['backoff_seconds'])-1)])
        if next_at>started_at+timedelta(hours=policy['max_age_hours']):return 'FAILED_TERMINAL','RETRY_WINDOW_EXPIRED',None
        return 'FAILED_RETRYABLE','TRANSIENT_SOURCE_FAILURE',next_at
    reason=next((e.get('reason_code') or e.get('kind') for s in result.get('sources',[]) for e in s.get('failures',[])),None)
    if status=='PARTIAL_SUCCESS':return 'PARTIAL_SUCCESS',reason or 'INCOMPLETE_TASK',None
    return 'FAILED_TERMINAL',reason or result.get('error') or 'UNCLASSIFIED_FAILURE',None


def _legacy(c,claim):
    state=claim['state']
    if state=='FAILED':state='FAILED_TERMINAL'
    elif state=='SUCCESS' and (claim['result'] or {}).get('ingestion_status')=='PARTIAL_SUCCESS':state='PARTIAL_SUCCESS'
    return c.execute("insert into startup_radar.schedule_task_attempts(task_key,attempt_number,kind,state,reason_code,result,origin,created_at,started_at,finished_at) "
        "values(%s,1,%s,%s,'LEGACY_UNCLASSIFIED',%s,'LEGACY_SNAPSHOT',%s,%s,%s) returning *",
        (claim['task_key'],claim['kind'],state,Jsonb(claim['result']),claim['created_at'],claim['created_at'],claim['finished_at'])).fetchone()


def observation(attempt,at):
    state=attempt['state']
    return {'key':attempt['task_key'],'attempt_id':str(attempt['id']),'attempt':attempt['attempt_number'],
            'state':state,'due':True,'already_successful':state=='SUCCESS',
            'unresolved_failure':state in ('FAILED_RETRYABLE','FAILED_TERMINAL','PARTIAL_SUCCESS','UNCERTAIN'),
            'retry_scheduled':state=='FAILED_RETRYABLE' and attempt['next_retry_at'] is not None,
            'terminal_failure':state=='FAILED_TERMINAL','currently_running':state=='RUNNING',
            'reason_code':attempt['reason_code'],
            'next_retry_at':attempt['next_retry_at'].isoformat() if attempt['next_retry_at'] else None,
            'execution_id':str(attempt['execution_id']) if attempt['execution_id'] else None}


def begin_attempt(db,kind,key,at,policy,execution_id=None):
    with db.transaction() as c:
        inserted=c.execute("insert into startup_radar.schedule_claims(task_key,kind,state,created_at) values(%s,%s,'RUNNING',%s) on conflict do nothing returning task_key",(key,kind,at)).fetchone()
        claim=c.execute('select * from startup_radar.schedule_claims where task_key=%s for update',(key,)).fetchone()
        latest=c.execute('select * from startup_radar.schedule_task_attempts where task_key=%s order by attempt_number desc limit 1',(key,)).fetchone()
        if not latest and not inserted:latest=_legacy(c,claim)
        if latest:
            if latest['state']=='PENDING':
                row=c.execute("update startup_radar.schedule_task_attempts set state='RUNNING',execution_id=%s,started_at=%s where id=%s returning *",(execution_id,at,latest['id'])).fetchone()
                c.execute("update startup_radar.schedule_claims set state='RUNNING',finished_at=null where task_key=%s",(key,))
                return row,observation(row,at)
            if latest['state']!='FAILED_RETRYABLE' or not latest['next_retry_at'] or at<latest['next_retry_at']:
                return None,observation(latest,at)
            if latest['attempt_number']>=policy['max_attempts'] or at>claim['created_at']+timedelta(hours=policy['max_age_hours']):
                reason='RETRY_EXHAUSTED' if latest['attempt_number']>=policy['max_attempts'] else 'RETRY_WINDOW_EXPIRED'
                # Close retry eligibility, retaining the original failure payload.
                closed=c.execute("update startup_radar.schedule_task_attempts set state='FAILED_TERMINAL',reason_code=%s,next_retry_at=null where id=%s returning *",(reason,latest['id'])).fetchone()
                c.execute("insert into startup_radar.admin_audit(action,entity_id,detail) values('SCHEDULE_RETRY_CLOSED',%s,%s)",
                          (str(latest['id']),Jsonb({'previous_reason':latest['reason_code'],'reason':reason})))
                return None,observation(closed,at)
        number=latest['attempt_number']+1 if latest else 1
        row=c.execute("insert into startup_radar.schedule_task_attempts(task_key,attempt_number,kind,state,execution_id,previous_attempt_id,origin,created_at,started_at) "
            "values(%s,%s,%s,'RUNNING',%s,%s,%s,%s,%s) returning *",
            (key,number,kind,execution_id,latest['id'] if latest else None,'AUTO_RETRY' if latest else 'SCHEDULED',at,at)).fetchone()
        c.execute("update startup_radar.schedule_claims set state='RUNNING',finished_at=null where task_key=%s",(key,))
    return row,observation(row,at)


def finish_attempt(db,attempt,result,policy,at):
    with db.transaction() as c:
        claim=c.execute('select created_at from startup_radar.schedule_claims where task_key=%s for update',(attempt['task_key'],)).fetchone()
        state,reason,retry_at=classify_result(attempt['kind'],result,attempt['attempt_number'],policy,claim['created_at'],at)
        row=c.execute("update startup_radar.schedule_task_attempts set state=%s,reason_code=%s,next_retry_at=%s,result=%s,finished_at=%s "
            "where id=%s and state='RUNNING' returning *",(state,reason,retry_at,Jsonb(result),at,attempt['id'])).fetchone()
        if not row:raise ValueError('Scheduled attempt ownership changed')
        claim_state='FAILED' if state.startswith('FAILED_') else state
        c.execute('update startup_radar.schedule_claims set state=%s,finished_at=%s,result=%s where task_key=%s',
                  (claim_state,at,Jsonb(result),attempt['task_key']))
    return observation(row,at)


def pending_retries(db,at):
    with db.transaction() as c:
        return c.execute("select a.kind,a.task_key from startup_radar.schedule_task_attempts a where a.kind='INGEST' "
            "and a.state in ('PENDING','FAILED_RETRYABLE') and not exists(select 1 from startup_radar.schedule_task_attempts newer "
            "where newer.task_key=a.task_key and newer.attempt_number>a.attempt_number) order by a.created_at").fetchall()


def request_ingest_retry(db,key,note):
    """Explicit operator request, no ingestion or delivery. Never unlock a live owner."""
    from radar.executions import LOCK_KEY,owner_identity
    if not 5<=len(note.strip())<=500:raise ValueError('An operator reason of 5..500 characters is required')
    with db.transaction() as c:
        if not c.execute('select pg_try_advisory_xact_lock(%s) acquired',(LOCK_KEY,)).fetchone()['acquired']:
            raise ValueError('An ownership operation is running')
        if c.execute('select 1 from startup_radar.worker_executions where finished_at is null').fetchone():
            raise ValueError('Verify and recover the active execution owner first')
        claim=c.execute('select * from startup_radar.schedule_claims where task_key=%s for update',(key,)).fetchone()
        if not claim or claim['kind']!='INGEST':raise ValueError('An existing INGEST claim is required')
        latest=c.execute('select * from startup_radar.schedule_task_attempts where task_key=%s order by attempt_number desc limit 1',(key,)).fetchone()
        if not latest:latest=_legacy(c,claim)
        if latest['state']=='RUNNING':
            owner=c.execute('select state from startup_radar.worker_executions where id=%s and finished_at is not null',(latest['execution_id'],)).fetchone() if latest['execution_id'] else None
            if not owner:raise ValueError('Unresolved running attempt requires verified execution recovery')
            c.execute("update startup_radar.schedule_task_attempts set state='UNCERTAIN',reason_code='TERMINAL_OWNER_RECONCILED',finished_at=now() where id=%s",(latest['id'],))
        if latest['state'] in ('SUCCESS','PENDING'):raise ValueError('The task is successful or already queued')
        requested=c.execute("insert into startup_radar.schedule_task_attempts(task_key,kind,attempt_number,state,previous_attempt_id,origin,recovery_note) "
            "values(%s,'INGEST',%s,'PENDING',%s,'OPERATOR_RETRY',%s) returning id",(key,latest['attempt_number']+1,latest['id'],note.strip())).fetchone()
        c.execute("insert into startup_radar.admin_audit(action,entity_id,detail) values('SCHEDULE_INGEST_RETRY',%s,%s)",
                  (key,Jsonb({'attempt_id':str(requested['id']),'previous_attempt_id':str(latest['id']),'reason':note.strip(),'operator':owner_identity()})))
    return {'status':'SUCCESS','state':'PENDING','attempt_id':str(requested['id']),'delivery':'DISABLED','executed':False}
