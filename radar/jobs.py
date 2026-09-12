"""External job dispatch is explicit, persisted, and never reports a timeout as success."""
import os
import requests
from psycopg.types.json import Jsonb


def dispatch_job(db,kind,source_slug=None,user_id=None):
    token=os.environ.get('RADAR_GITHUB_TOKEN')
    repo=os.environ.get('GITHUB_REPOSITORY','jey24960-sketch/startup-radar')
    ref=os.environ.get('RADAR_GITHUB_REF','main')
    if kind not in ('INGEST','DIGEST','REMINDER','HIGH_FIT','TICK'):raise ValueError('Unsupported job type')
    with db.transaction() as c:
        job=c.execute('insert into startup_radar.job_requests(kind,source_slug,requested_by) values(%s,%s,%s) returning *',(kind,source_slug,user_id)).fetchone()
    if not token:
        error='RADAR_GITHUB_TOKEN is required for GitHub job dispatch'
        with db.transaction() as c:c.execute("update startup_radar.job_requests set state='FAILED',result=%s,finished_at=now() where id=%s",(Jsonb({'error':error}),job['id']))
        return {'job_id':str(job['id']),'state':'FAILED','error':error}
    try:
        response=requests.post(f'https://api.github.com/repos/{repo}/actions/workflows/startup_radar_v2.yml/dispatches',
            headers={'Authorization':f'Bearer {token}','Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'},
            json={'ref':ref,'inputs':{'job_id':str(job['id']),'kind':kind,'source_slug':source_slug or ''}},timeout=20)
        if response.status_code==204:
            with db.transaction() as c:current=c.execute('select state from startup_radar.job_requests where id=%s',(job['id'],)).fetchone()
            return {'job_id':str(job['id']),'state':current['state']}
        state='FAILED';error=f'GitHub rejected workflow dispatch (HTTP {response.status_code})'
    except requests.RequestException:state='UNCERTAIN';error='GitHub dispatch outcome unknown; inspect Actions before retrying'
    with db.transaction() as c:
        changed=c.execute("update startup_radar.job_requests set state=%s,result=%s,finished_at=now() where id=%s and state='REQUESTED' returning state",
            (state,Jsonb({'error':error}),job['id'])).fetchone()
        current=changed or c.execute('select state from startup_radar.job_requests where id=%s',(job['id'],)).fetchone()
    return {'job_id':str(job['id']),'state':current['state'],**({'error':error} if changed else {'dispatch_error':error})}


def cancel_job(db,job_id,note,user_id):
    """Retire a queued/orphan request; late dispatches cannot execute its ID."""
    from radar.services import require_admin
    require_admin(db,user_id)
    if not 5<=len(note.strip())<=500:raise ValueError('A recovery note of 5..500 characters is required')
    with db.transaction() as c:
        if not c.execute('select pg_try_advisory_xact_lock(782394202) acquired').fetchone()['acquired']:
            raise ValueError('A V2 job is currently running; cancellation cannot race execution')
        if c.execute('select 1 from startup_radar.worker_executions where finished_at is null').fetchone():
            raise ValueError('A V2 job is currently running or requires verified execution recovery')
        job=c.execute('select * from startup_radar.job_requests where id=%s for update',(job_id,)).fetchone()
        if not job:raise LookupError('Job request not found')
        if job['state']=='CANCELLED':return {'job_id':str(job_id),'state':'CANCELLED','changed':False}
        if job['state'] not in ('REQUESTED','RUNNING','UNCERTAIN'):raise ValueError('Only queued, orphaned or uncertain requests can be cancelled')
        previous={'state':job['state'],'result':job['result'],'note':note.strip()}
        c.execute("update startup_radar.job_requests set state='CANCELLED',finished_at=now(),result=%s where id=%s",
            (Jsonb({'reason':'Administrator cancelled local request','previous':previous}),job_id))
        c.execute('insert into startup_radar.admin_audit(actor_id,action,entity_id,detail) values(%s,%s,%s,%s)',
            (user_id,'CANCEL_JOB',str(job_id),Jsonb(previous)))
    return {'job_id':str(job_id),'state':'CANCELLED','changed':True}
