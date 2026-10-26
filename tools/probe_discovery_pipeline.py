"""Read-only opt-in pipeline/session probe; never collects or sends notices."""
import json
import re
import psycopg
from psycopg.pq import PipelineStatus, TransactionStatus
from radar.database import Database
from radar.discovery_connection import discovery_database_options


def _require_idle(connection):
    if connection.info.transaction_status != TransactionStatus.IDLE:
        raise RuntimeError('Pipeline probe did not restore an idle transaction')
    if connection.info.pipeline_status != PipelineStatus.OFF:
        raise RuntimeError('Pipeline probe did not exit pipeline mode')


def probe_database(db):
    """Read only. The forced SQL failure must roll back before reuse succeeds."""
    if not db.pipeline:
        raise ValueError('Pipeline probe requires explicit discovery pipeline opt-in')
    with db.session():
        with db.transaction() as connection:
            connection.execute('set transaction read only')
            if connection.info.pipeline_status != PipelineStatus.ON:
                raise RuntimeError('Pipeline probe did not enter pipeline mode')
            first = connection.execute('select 1 as value')
            second = connection.execute('select 2 as value')
            if first.fetchone()['value'] != 1 or second.fetchone()['value'] != 2:
                raise RuntimeError('Pipeline probe received mismatched query results')
        _require_idle(connection)
        failed = False
        try:
            with db.transaction() as failing:
                failing.execute('set transaction read only')
                # No fetch: the error arrives when the inner pipeline exits.
                failing.execute('select 1/0')
        except psycopg.errors.DivisionByZero:
            failed = True
        if not failed:
            raise RuntimeError('Pipeline probe did not observe the expected SQL failure')
        _require_idle(connection)
        with db.transaction() as recovered:
            recovered.execute('set transaction read only')
            if recovered is not connection or recovered.execute('select 3 as value').fetchone()['value'] != 3:
                raise RuntimeError('Pipeline probe failed to reuse the recovered connection')
        _require_idle(connection)
    return {'status': 'SUCCESS', 'pipeline': True, 'checks': {
        'ordered_selects': True, 'delayed_error_rollback': True,
        'next_transaction_reused_connection': True, 'idle_after_transactions': True,
        'pipeline_off_between_transactions': True, 'read_only': True,
    }}


def main():
    try:
        options = discovery_database_options()
        if options.get('pipeline') is not True:
            raise ValueError('Pipeline probe requires explicit discovery pipeline opt-in')
        result = probe_database(Database(**options))
    except Exception as error:
        # Connection errors may include endpoint/account text. Emit only class
        # and the standard five-character SQLSTATE, never str(error) or conninfo.
        state = getattr(error, 'sqlstate', None)
        result = {'status': 'FAILED', 'error_type': type(error).__name__}
        if isinstance(state, str) and re.fullmatch(r'[A-Z0-9]{5}', state):
            result['sqlstate'] = state
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['status'] == 'SUCCESS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
