"""Explicit discovery-only routing to a pipeline-compatible Supabase endpoint.

Never print, log, persist, or include the returned connection info in an error.
This helper does not connect and does not alter the process environment.
"""
import os
import re
from psycopg.conninfo import conninfo_to_dict, make_conninfo

SETTING = 'RADAR_DISCOVERY_SESSION_PIPELINE'
_SHARED_POOLER = re.compile(r'^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.pooler\.supabase\.com$', re.I)
_DIRECT_DATABASE = re.compile(r'^db\.[a-z0-9]+\.supabase\.co$', re.I)


def discovery_database_options(environ=None):
    """Return Database kwargs; default behaviour is unchanged unless opted in.

    Only official shared poolers may move from 6543 (transaction mode) to
    5432 (session mode), retaining exactly the same host, account and options.
    Existing official direct/session endpoints on 5432 remain unchanged.
    Arbitrary endpoints, services, hostaddr overrides and multi-host strings
    cannot be silently treated as a compatible session connection.
    """
    environ = os.environ if environ is None else environ
    setting = environ.get(SETTING, '')
    if not isinstance(setting, str):
        raise ValueError('Discovery pipeline opt-in must be true or false')
    setting = setting.strip().lower()
    if setting in ('', 'false'):
        return {}
    if setting != 'true':
        raise ValueError('Discovery pipeline opt-in must be true or false')
    url = environ.get('DATABASE_URL')
    if not isinstance(url, str) or not url:
        raise ValueError('DATABASE_URL is required for discovery pipeline opt-in')
    try:
        parameters = conninfo_to_dict(url)
    except Exception:
        # libpq parse errors can contain the supplied conninfo. Suppress their
        # original text and chaining so credentials never enter CLI output.
        raise ValueError('Invalid discovery database connection configuration') from None
    host = parameters.get('host', '')
    port = parameters.get('port') or '5432'
    if (parameters.get('hostaddr') or parameters.get('service')
            or environ.get('PGHOSTADDR') or environ.get('PGSERVICE')):
        raise ValueError('Discovery pipeline requires one explicit supported database endpoint')
    shared = bool(_SHARED_POOLER.fullmatch(host))
    direct = bool(_DIRECT_DATABASE.fullmatch(host))
    if shared and port == '6543':
        parameters['port'] = '5432'
        return {'url': make_conninfo(**parameters), 'pipeline': True}
    if port == '5432' and (shared or direct):
        if not parameters.get('port'):
            # Make the inspected port explicit; a PGPORT environment override
            # must not route an opted-in connection back to transaction mode.
            parameters['port'] = '5432'
            url = make_conninfo(**parameters)
        return {'url': url, 'pipeline': True}
    raise ValueError('Discovery pipeline requires a supported direct or session-mode endpoint')
