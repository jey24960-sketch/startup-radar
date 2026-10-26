"""Internal daily discovery; members continue reading curated weekly notices."""
from datetime import datetime, timedelta
from core.clock import SEOUL
from psycopg.types.json import Jsonb
from radar.executions import claim_execution, finish_execution
from radar.ingestion import ingest

SETTING = 'daily_discovery'


def discovery_slot(at):
    if at is None or at.tzinfo is None:
        raise ValueError('Aware discovery clock required')
    local = at.astimezone(SEOUL)
    hour = 18 if local.hour >= 18 else 6
    day = local - timedelta(days=1) if local.hour < 6 else local
    if local.hour < 6: hour = 18
    return day.replace(hour=hour, minute=0, second=0, microsecond=0)


def discovery_sources(sources, settings=None):
    """Traverse official API scope without the weekly one-page override.

    Do not stop at the first known ID: API ordering is not a proven cursor.
    Reaching a safety cap remains a visible incomplete-source outcome.
    """
    settings = settings or {}
    result = []
    for source in sources:
        if not source.get('enabled', True): continue
        config = dict(source.get('config') or {})
        if source['adapter'] in ('KSTARTUP', 'BIZINFO'):
            maximum = settings.get('kstartup_max_pages' if source['adapter']=='KSTARTUP' else 'bizinfo_max_pages',
                                   10 if source['adapter']=='KSTARTUP' else 20)
            if type(maximum) is not int or not 1 <= maximum <= 30:
                raise ValueError('Discovery page cap must be an integer in 1..30')
            config.update(scope='OPEN' if source['adapter']=='KSTARTUP' else 'API_DEFAULT',
                          page_size=100, max_pages=maximum)
            if source['adapter']=='KSTARTUP':
                config['recent_announcement_pages']=2
            config.pop('weekly_policy', None)
        elif not (config.get('weekly_direct') is True and config.get('policy_status')=='APPROVED'):
            continue
        result.append({**source, 'config': config})
    return result


def run_discovery(db, transport=None, at=None, collector=None):
    """Collect facts without AI/OCR/personalization; at most one owner per slot.

    The first rollout run should omit transport. Enable exceptional notices only
    after that baseline finishes, so imported history never becomes a broadcast.
    """
    collector = collector or ingest
    with db.transaction() as c:
        config_row = c.execute('select value from startup_radar.runtime_settings where key=%s',(SETTING,)).fetchone()
        config = config_row['value'] if config_row else {}
        reference = c.execute('select now() as at').fetchone()['at']
    if not config.get('enabled'):
        return {'status':'SUCCESS','state':'DISCOVERY_DISABLED','executed':False}
    if at is not None:
        if at.tzinfo is None: raise ValueError('Aware discovery clock required')
        reference = at
    slot = discovery_slot(reference)
    claim = claim_execution(db, 'DISCOVER')
    if 'execution_id' not in claim: return claim
    execution_id = claim['execution_id']
    result = None
    try:
        with db.session():
            with db.transaction() as c:
                saved = c.execute('insert into startup_radar.discovery_slots(slot_start,execution_id) values(%s,%s) '
                                  'on conflict(slot_start) do nothing returning slot_start', (slot,execution_id)).fetchone()
                if not saved:
                    result = {'status':'SUCCESS','state':'DUPLICATE_DISCOVERY_SLOT','executed':False,'slot':slot.isoformat()}
                else:
                    sources = c.execute('select * from startup_radar.sources where enabled order by slug').fetchall()
            if result is None:
                sources = discovery_sources(sources,config)
                if not {'KSTARTUP','BIZINFO'} <= {s['adapter'] for s in sources}:
                    raise ValueError('Both official APIs must be configured for discovery')
                collection = collector(db,sources,trigger='daily-discovery',structured_only=True)
                result = {'status':collection['status'],'state':'DISCOVERY_COMPLETED','executed':True,
                          'slot':slot.isoformat(),'ingestion_run_id':collection['id'], 'sources':collection['sources']}
                if collection['status'] != 'FAILED':
                    from radar.early_announcements import plan_early_notices, announce_early
                    planned = plan_early_notices(db)
                    result['early_notice'] = planned
                    if planned.get('notice_id') and transport is not None:
                        result['early_delivery'] = announce_early(db,planned['notice_id'],transport=transport)
                        if result['early_delivery'].get('state')=='UNCERTAIN':
                            result['status']='UNCERTAIN'
                        elif result['early_delivery'].get('state')=='FAILED':
                            result['status']='PARTIAL_SUCCESS'
            with db.transaction() as c:
                c.execute('update startup_radar.discovery_slots set finished_at=now(),result=%s where execution_id=%s',
                          (Jsonb(result),execution_id))
    except Exception as error:
        result = {'status':'FAILED','reason':type(error).__name__,'slot':slot.isoformat()}
    try: finish_execution(db,execution_id,result)
    except Exception as error:
        return {'status':'UNCERTAIN','execution_id':str(execution_id),'reason':type(error).__name__}
    return {**result,'execution_id':str(execution_id)}
