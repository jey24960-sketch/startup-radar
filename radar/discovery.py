"""Daily discovery and weekly publication share durable ownership, not their clocks."""
from datetime import timedelta
from urllib.parse import urlsplit
from psycopg.types.json import Jsonb
from core.clock import now,SEOUL
from radar.executions import claim_execution,finish_execution
from radar.ingestion import ingest


def daily_due(db,at,execution_id=None):
    local=at.astimezone(SEOUL)
    with db.transaction() as c:
        config=c.execute('select * from startup_radar.discovery_schedule where singleton'+(' for update' if execution_id else '')).fetchone()
        if not config['enabled'] or local.hour<config['daily_hour']:return False
        if c.execute('select 1 from startup_radar.discovery_attempts where day=%s',(local.date(),)).fetchone():return False
        if execution_id:
            return bool(c.execute('insert into startup_radar.discovery_attempts(day,execution_id) values(%s,%s) on conflict do nothing returning day',(local.date(),execution_id)).fetchone())
        return True


def run_discovery(db,at=None,scheduled=False,collector=None):
    at=at or now()
    if at.tzinfo is None:raise ValueError('Aware clock required')
    if scheduled and not daily_due(db,at):return {'status':'SUCCESS','state':'NOT_DUE','executed':False}
    owner=claim_execution(db,'INGEST')
    if 'execution_id' not in owner:return owner
    result=None
    try:
        if scheduled and not daily_due(db,at,owner['execution_id']):result={'status':'SUCCESS','state':'NOT_DUE','executed':False}
        else:
            with db.transaction() as c:
                sources=c.execute("select s.* from startup_radar.sources s where enabled and (adapter in ('KSTARTUP','BIZINFO') or config->>'opportunity_channel'='true') order by slug").fetchall()
            result=(collector or ingest)(db,sources,trigger='daily-discovery',structured_only=True)
            # Daily publication reads the stored projection. Do not persist a
            # second unbounded copy of programme snapshots (or native UUIDs).
            result={k:v for k,v in result.items() if k!='weekly_programs'}
            with db.transaction() as c:
                for outcome in result.get('sources',[]):
                    reason=next(iter(outcome.get('failures',[])),{}).get('reason_code')
                    state='CONNECTED' if outcome['status']=='SUCCESS' else 'PARTIAL' if outcome.get('parsed') else 'ACCESS_RESTRICTED' if reason in ('ROBOTS_DISALLOWED','HTTP_4XX','POLICY_REVIEW') else 'CONFIGURATION_REQUIRED' if reason in ('NOT_CONFIGURED','CONFIGURATION','DETAIL_PARSE','LIST_PARSE') else 'TEMPORARY_ERROR'
                    c.execute('update startup_radar.source_channels set connection_state=%s,last_checked_at=now(),last_reason=%s,proof=%s where source_id=%s',
                        (state,reason,Jsonb({'run_id':result['id'],'status':outcome['status'],'parsed':outcome.get('parsed',0),'coverage':outcome.get('coverage',{})}),outcome['source_id']))
            resolve_collected_submissions(db)
    except Exception as error:result={'status':'FAILED','reason':type(error).__name__}
    finish_execution(db,owner['execution_id'],result)
    return {**result,'execution_id':owner['execution_id']}


def resolve_collected_submissions(db):
    # Verification comes from the same independently fetched official source.
    # A submission never inserts a hostname, channel or publication automatically.
    with db.transaction() as c:
        rows=c.execute("select * from startup_radar.opportunity_submissions where state in ('REVIEW','CONNECTION_REQUIRED') order by created_at limit 100").fetchall()
        for row in rows:
            matches=c.execute("select o.program_id from startup_radar.opportunity_records o where confirmed and duplicate_of is null and (facts->>'official_url'=%s or facts->>'application_url'=%s or exists(select 1 from startup_radar.program_sources s where s.program_id=o.program_id and s.official_detail_url=%s))",(row['official_url'],)*3).fetchall()
            if len(matches)==1:
                c.execute("update startup_radar.opportunity_submissions set state='APPLIED',program_id=%s,operator_note='Official source independently collected',updated_at=now(),revision=revision+1 where id=%s",(matches[0]['program_id'],row['id']))
            else:
                approved=c.execute('select 1 from startup_radar.institutions where %s=any(approved_hosts) and policy_status=\'APPROVED\'',(urlsplit(row['official_url']).hostname,)).fetchone()
                if not approved and row['state']!='CONNECTION_REQUIRED':
                    c.execute("update startup_radar.opportunity_submissions set state='CONNECTION_REQUIRED',operator_note='Official domain/channel review required',updated_at=now(),revision=revision+1 where id=%s",(row['id'],))


def run_calendar(db,transport=None,at=None):
    from radar.weekly import run_weekly
    at=at or now()
    daily=run_discovery(db,at=at,scheduled=True)
    with db.transaction() as c:
        use_catalog=c.execute("select enabled or exists(select 1 from startup_radar.ingestion_runs where trigger_type='daily-discovery') use_catalog from startup_radar.discovery_schedule where singleton").fetchone()['use_catalog']
    # An additive rollout with daily discovery still disabled must preserve the
    # existing official-API weekly job. Once discovery starts, require freshness.
    weekly=run_weekly(db,transport,at=at,scheduled=True,from_catalog=use_catalog)
    return {'status':'SUCCESS' if daily['status']==weekly['status']=='SUCCESS' else 'PARTIAL_SUCCESS',
            'daily':daily,'weekly':weekly}
