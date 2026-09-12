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
        job=c.execute('insert into radar.job_requests(kind,source_slug,requested_by) values(%s,%s,%s) returning *',(kind,source_slug,user_id)).fetchone()
    if not token:
        error='RADAR_GITHUB_TOKEN is required for GitHub job dispatch'
        with db.transaction() as c:c.execute("update radar.job_requests set state='FAILED',result=%s,finished_at=now() where id=%s",(Jsonb({'error':error}),job['id']))
        return {'job_id':str(job['id']),'state':'FAILED','error':error}
    try:
        response=requests.post(f'https://api.github.com/repos/{repo}/actions/workflows/startup_radar_v2.yml/dispatches',
            headers={'Authorization':f'Bearer {token}','Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'},
            json={'ref':ref,'inputs':{'job_id':str(job['id']),'kind':kind,'source_slug':source_slug or ''}},timeout=20)
        if response.status_code==204:return {'job_id':str(job['id']),'state':'REQUESTED'}
        state='FAILED';error=f'GitHub rejected workflow dispatch (HTTP {response.status_code})'
    except requests.RequestException:state='UNCERTAIN';error='GitHub dispatch outcome unknown; inspect Actions before retrying'
    with db.transaction() as c:c.execute('update radar.job_requests set state=%s,result=%s,finished_at=now() where id=%s',(state,Jsonb({'error':error}),job['id']))
    return {'job_id':str(job['id']),'state':state,'error':error}
