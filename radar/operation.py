"""Operator runtime controls read by the worker before any side effect.

`radar_operation` is the normal pause/resume switch operators flip from the
GFC admin page; `vars.RADAR_V2_ENABLED` stays the external emergency gate in
GitHub Actions. `radar_visibility` decides who may read published content and,
for the worker, whether the official Telegram channel may be used (PRIVATE
suppresses it). Missing rows mean today's defaults: running, MEMBERS_ONLY.
"""
from psycopg.types.json import Jsonb

OPERATION_KEY = 'radar_operation'
VISIBILITY_KEY = 'radar_visibility'
VISIBILITY_MODES = ('PRIVATE', 'MEMBERS_ONLY', 'PUBLIC')


def _setting(c, key):
    row = c.execute('select value from startup_radar.runtime_settings where key=%s', (key,)).fetchone()
    value = row['value'] if row else None
    return value if isinstance(value, dict) else {}


def operation_state(c):
    value = _setting(c, OPERATION_KEY)
    enabled = value.get('enabled')
    return {'enabled': True if enabled is None else bool(enabled), 'reason': value.get('reason'), 'version': value.get('version')}


def visibility_mode(c):
    mode = _setting(c, VISIBILITY_KEY).get('mode')
    return mode if mode in VISIBILITY_MODES else 'MEMBERS_ONLY'


def paused_result(c, kind):
    """Honest no-op for a schedule that fired while paused.

    Called inside the execution claim transaction, before any row is written:
    nothing is claimed, collected, published or sent, and no ingestion_run
    exists for it. Only an audit row records that the run was skipped so the
    operator can see the pause took effect. Resume never replays these.
    """
    state = operation_state(c)
    if state['enabled']:
        return None
    c.execute("insert into startup_radar.admin_audit(action,entity_id,detail) values('RADAR_RUN_SKIPPED_PAUSED',%s,%s)",
              (OPERATION_KEY, Jsonb({'kind': kind, 'reason': state['reason'], 'operation_version': state['version']})))
    return {'status': 'PAUSED', 'reason': 'RADAR_OPERATION_PAUSED', 'kind': kind, 'executed': False}
