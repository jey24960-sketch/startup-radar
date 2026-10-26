import os
from uuid import uuid4
import pytest

from test_database import db
from radar.source_check import check_discovery_sources


pytestmark = pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),
                                reason='Explicit test database required')


def enable(db):
    with db.transaction() as c:
        c.execute("insert into startup_radar.runtime_settings(key,value) values('daily_discovery','{\"enabled\":true}') on conflict(key) do update set value=excluded.value")
        for slug, adapter in [('test-kstartup', 'KSTARTUP'), ('test-bizinfo', 'BIZINFO')]:
            c.execute('insert into startup_radar.sources(slug,name,adapter,config) values(%s,%s,%s,%s)',
                      (slug, slug, adapter, '{}'))


def test_source_check_is_nonpublishing_and_does_not_consume_scheduled_slot(db, monkeypatch):
    enable(db)
    monkeypatch.setattr('radar.early_announcements.plan_early_notices',
                        lambda *_: pytest.fail('Source check must not plan an early notice'))
    calls = []
    def collect(_db, sources, **kwargs):
        calls.append(kwargs)
        assert all(s['config']['max_pages'] > 1 for s in sources)
        return {'id': str(uuid4()), 'status': 'SUCCESS', 'sources': []}
    result = check_discovery_sources(db, collector=collect)
    assert result['state'] == 'DISCOVERY_SOURCE_CHECK_COMPLETED'
    assert calls == [{'trigger': 'discovery-source-check', 'structured_only': True}]
    with db.transaction() as c:
        for table in ('discovery_slots', 'weekly_briefings', 'early_notices', 'notification_runs'):
            assert c.execute(f'select count(*) n from startup_radar.{table}').fetchone()['n'] == 0
        assert c.execute('select state from startup_radar.worker_executions').fetchone()['state'] == 'SUCCESS'


def test_disabled_and_paused_source_checks_never_collect(db):
    fail = lambda *_args, **_kwargs: pytest.fail('Disabled/paused source check collected')
    assert check_discovery_sources(db, fail)['state'] == 'DISCOVERY_DISABLED'
    enable(db)
    with db.transaction() as c:
        c.execute("update startup_radar.runtime_settings set value='{\"enabled\":false}' where key='radar_operation'")
    result = check_discovery_sources(db, fail)
    assert result['status'] == 'PAUSED'
