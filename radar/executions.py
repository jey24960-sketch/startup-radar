"""Durable batch ownership; an uncertain/crashed process never expires itself."""
import os
import socket
from datetime import date,datetime
from uuid import UUID,uuid4
from psycopg.types.json import Jsonb
from radar.operation import paused_result

LOCK_KEY=782394202


def owner_identity():
    # Operator diagnostics only; never copy arbitrary environment/credentials.
    return {'host':socket.gethostname(),'pid':os.getpid(),
            'github_run_id':os.environ.get('GITHUB_RUN_ID'),
            'github_run_attempt':os.environ.get('GITHUB_RUN_ATTEMPT')}


def weekly_schedule_arguments(scheduler_request_id=None,expected_week_start=None):
    """Validate the explicit scheduler identity without accessing a database."""
    if scheduler_request_id is None and expected_week_start is None:return None,None
    if scheduler_request_id is None or expected_week_start is None:
        raise ValueError('Scheduler request ID and expected week start must be supplied together')
    request_id=UUID(str(scheduler_request_id))
    if isinstance(expected_week_start,datetime):raise ValueError('Expected week start must be an ISO Monday date')
    start=date.fromisoformat(str(expected_week_start))
    if str(expected_week_start)!=start.isoformat() or start.weekday()!=0:
        raise ValueError('Expected week start must be an ISO Monday date')
    return request_id,start


def claim_execution(db,kind,source_slug=None,job_id=None,scheduler_request_id=None,expected_week_start=None):
    execution_id=uuid4()
    job_id=UUID(str(job_id)) if job_id else None
    request_id,expected_week=weekly_schedule_arguments(scheduler_request_id,expected_week_start)
    if request_id and (kind!='WEEKLY' or source_slug is not None or job_id is not None):
        raise ValueError('Scheduled weekly requests cannot be used for another job kind or source')
    schedule_metadata={}
    with db.transaction() as c:
        # Serialize only the claim/cancellation/recovery transaction. The row
        # remains authoritative after this short-lived connection closes.
        if not c.execute('select pg_try_advisory_xact_lock(%s) acquired',(LOCK_KEY,)).fetchone()['acquired']:
            return {'status':'FAILED','error':'Another V2 job is running; request remains pending'}
        if request_id:
            clock=c.execute("select date_trunc('week',now() at time zone 'Asia/Seoul')::date week_start,now() reference_at").fetchone()
            request=c.execute('select id,week_start,scheduled_at,execution_id,suppressed_reason from startup_radar.weekly_schedule_requests where id=%s for update',
                              (request_id,)).fetchone()
            if not request or request['week_start']!=expected_week:
                return {'status':'FAILED','state':'INVALID_SCHEDULE_REQUEST','executed':False,'scheduler_request_id':str(request_id)}
            schedule_metadata={'scheduler_request_id':str(request_id),'expected_week_start':expected_week.isoformat()}
            if request['suppressed_reason']:
                return {'status':'PAUSED','state':'SKIPPED_PAUSED','executed':False,**schedule_metadata}
            if request['execution_id']:
                return {'status':'SUCCESS','state':'DUPLICATE_SCHEDULE_REQUEST','executed':False,
                        'previous_execution_id':str(request['execution_id']),**schedule_metadata}
            if expected_week!=clock['week_start']:
                return {'status':'SUCCESS','state':'STALE_SCHEDULE_REQUEST','executed':False,**schedule_metadata}
            if clock['reference_at']<request['scheduled_at']:
                return {'status':'SUCCESS','state':'SCHEDULE_NOT_DUE','executed':False,**schedule_metadata}
            # Publication uses the same verified server clock as the request claim,
            # so a delayed worker or a local clock cannot publish another week.
            schedule_metadata['reference_at']=clock['reference_at'].isoformat()
        # Operator pause is decided here, under the same lock and before any
        # claim, so every production job kind honours it without extra round-trips.
        paused=paused_result(c,kind)
        if paused:
            if request_id:
                c.execute("update startup_radar.weekly_schedule_requests set suppressed_reason='OPERATOR_PAUSED' where id=%s",(request_id,))
            return {**paused,**schedule_metadata}
        active=c.execute('select id from startup_radar.worker_executions where finished_at is null').fetchone()
        if active:
            return {'status':'FAILED','error':'Another V2 job is running or requires verified recovery; request remains pending',
                    'active_execution_id':str(active['id'])}
        if job_id:
            job=c.execute("update startup_radar.job_requests set state='RUNNING' where id=%s and state in ('REQUESTED','UNCERTAIN') "
                          'and kind=%s and source_slug is not distinct from %s returning id',(job_id,kind,source_slug)).fetchone()
            if not job:return {'status':'SUCCESS','state':'DUPLICATE_OR_MISMATCHED_JOB','executed':False}
        c.execute('insert into startup_radar.worker_executions(id,kind,source_slug,job_id,owner) values(%s,%s,%s,%s,%s)',
                  (execution_id,kind,source_slug,job_id,Jsonb(owner_identity())))
        if request_id:
            c.execute('update startup_radar.weekly_schedule_requests set execution_id=%s where id=%s',
                      (execution_id,request_id))
    # Do not return ownership until COMMIT succeeds. Lost commit acknowledgement
    # may leave a durable row, but must never start an unconfirmed executor.
    return {'execution_id':str(execution_id),**schedule_metadata}


def finish_execution(db,execution_id,result):
    if result.get('status') not in ('SUCCESS','PARTIAL_SUCCESS','FAILED','UNCERTAIN'):
        raise ValueError('Executor returned an invalid terminal status')
    with db.transaction() as c:
        row=c.execute("update startup_radar.worker_executions set state=%s,result=%s,finished_at=now() "
            "where id=%s and state='RUNNING' returning job_id",(result['status'],Jsonb(result),execution_id)).fetchone()
        if not row:raise ValueError('Execution ownership changed; inspect recovery before proceeding')
        if row['job_id']:
            c.execute("update startup_radar.job_requests set state=%s,result=%s,finished_at=now() where id=%s and state='RUNNING'",
                      (result['status'],Jsonb(result),row['job_id']))


def active_execution(db):
    with db.transaction() as c:
        return c.execute('select * from startup_radar.worker_executions where finished_at is null').fetchone()


def recover_execution(db,execution_id,note,confirmed_stopped=False):
    """Privileged operator action, not an age/heartbeat-based takeover.

    The caller must verify the recorded host/PID or Actions run has terminated.
    Database connection absence is insufficient evidence of process termination.
    """
    execution_id=UUID(str(execution_id))
    if not confirmed_stopped:raise ValueError('Verify the owner process has stopped before recovery')
    if not 5<=len(note.strip())<=500:raise ValueError('A recovery note of 5..500 characters is required')
    with db.transaction() as c:
        if not c.execute('select pg_try_advisory_xact_lock(%s) acquired',(LOCK_KEY,)).fetchone()['acquired']:
            raise ValueError('Another ownership operation is in progress')
        row=c.execute('select * from startup_radar.worker_executions where id=%s for update',(execution_id,)).fetchone()
        if not row:raise LookupError('Execution not found')
        if row['state']!='RUNNING':return {'status':'SUCCESS','changed':False,'state':row['state']}
        result={'status':'UNCERTAIN','reason':'Operator verified process termination; inspect partial effects before retry',
                'execution_id':str(execution_id)}
        c.execute("update startup_radar.worker_executions set state='ABANDONED',finished_at=now(),result=%s,recovery_note=%s where id=%s",
                  (Jsonb(result),note.strip(),execution_id))
        attempts=c.execute("update startup_radar.schedule_task_attempts set state='UNCERTAIN',reason_code='WORKER_TERMINATED',finished_at=now(), "
                           "result=coalesce(result,'{}') || %s where execution_id=%s and state='RUNNING' returning task_key",
                           (Jsonb(result),execution_id)).fetchall()
        for attempt in attempts:
            c.execute("update startup_radar.schedule_claims set state='UNCERTAIN',finished_at=now() where task_key=%s",(attempt['task_key'],))
        if row['job_id']:
            c.execute("update startup_radar.job_requests set state='UNCERTAIN',finished_at=now(),result=%s where id=%s and state='RUNNING'",
                      (Jsonb(result),row['job_id']))
    return {'status':'SUCCESS','changed':True,'state':'ABANDONED','execution_id':str(execution_id),'retry_dispatched':False}
