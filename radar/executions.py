"""Durable batch ownership; an uncertain/crashed process never expires itself."""
import os
import socket
from uuid import UUID,uuid4
from psycopg.types.json import Jsonb

LOCK_KEY=782394202


def owner_identity():
    # Operator diagnostics only; never copy arbitrary environment/credentials.
    return {'host':socket.gethostname(),'pid':os.getpid(),
            'github_run_id':os.environ.get('GITHUB_RUN_ID'),
            'github_run_attempt':os.environ.get('GITHUB_RUN_ATTEMPT')}


def claim_execution(db,kind,source_slug=None,job_id=None):
    execution_id=uuid4()
    job_id=UUID(str(job_id)) if job_id else None
    with db.transaction() as c:
        # Serialize only the claim/cancellation/recovery transaction. The row
        # remains authoritative after this short-lived connection closes.
        if not c.execute('select pg_try_advisory_xact_lock(%s) acquired',(LOCK_KEY,)).fetchone()['acquired']:
            return {'status':'FAILED','error':'Another V2 job is running; request remains pending'}
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
    # Do not return ownership until COMMIT succeeds. Lost commit acknowledgement
    # may leave a durable row, but must never start an unconfirmed executor.
    return {'execution_id':str(execution_id)}


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
