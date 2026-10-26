"""Non-publishing acquisition check after approved source/parser changes."""
from radar.discovery import SETTING, discovery_sources
from radar.executions import claim_execution, finish_execution
from radar.ingestion import ingest


def check_discovery_sources(db, collector=None):
    """Persist source facts only, respecting pause/owner gates and sending nothing.

    This does not consume or replace a scheduled discovery slot. It is separate
    from a slot retry: it can never create a weekly/early article or a delivery.
    """
    with db.transaction() as c:
        row = c.execute('select value from startup_radar.runtime_settings where key=%s',
                        (SETTING,)).fetchone()
        config = row['value'] if row else {}
    if not config.get('enabled'):
        return {'status': 'SUCCESS', 'state': 'DISCOVERY_DISABLED', 'executed': False}
    claim = claim_execution(db, 'DISCOVER')
    if 'execution_id' not in claim:
        return claim
    execution_id = claim['execution_id']
    try:
        with db.session():
            with db.transaction() as c:
                sources = c.execute('select * from startup_radar.sources where enabled order by slug').fetchall()
            sources = discovery_sources(sources, config)
            if not {'KSTARTUP', 'BIZINFO'} <= {s['adapter'] for s in sources}:
                raise ValueError('Both official APIs must be configured for discovery')
            collection = (collector or ingest)(db, sources, trigger='discovery-source-check', structured_only=True)
            result = {'status': collection['status'], 'state': 'DISCOVERY_SOURCE_CHECK_COMPLETED',
                      'executed': True, 'ingestion_run_id': collection['id'],
                      'sources': collection['sources']}
    except Exception as error:
        result = {'status': 'FAILED', 'reason': type(error).__name__, 'executed': True}
    try:
        finish_execution(db, execution_id, result)
    except Exception as error:
        return {'status': 'UNCERTAIN', 'execution_id': str(execution_id), 'reason': type(error).__name__}
    return {**result, 'execution_id': str(execution_id)}
