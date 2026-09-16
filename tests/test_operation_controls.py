"""Operator controls seen from the worker: pause/resume, PRIVATE visibility and
withdrawn briefings. Needs TEST_DATABASE_URL."""
import os
from datetime import datetime
from unittest.mock import Mock
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb
from core.clock import SEOUL
from radar import cli
from radar.operation import OPERATION_KEY, VISIBILITY_KEY, operation_state, visibility_mode
from radar.scheduler import run_job
from radar.weekly import announce, build_briefing, run_weekly
from test_database import db  # noqa: F401
from test_weekly import collection, configure_official_channel
from test_weekly_broadcast import delivered_transport, ledger

pytestmark = pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), reason='Explicit test database required')
AT = datetime(2026, 9, 15, 15, tzinfo=SEOUL)
CHAT = '@gfc_startup_radar'


def admin(db):
    user = uuid4()
    with db.transaction() as c:
        c.execute('insert into auth.users(id) values(%s)', (user,))
        c.execute("insert into public.test_gfc_roles values(%s,'admin')", (user,))
    return user


def set_operation(db, enabled, reason=None):
    with db.transaction() as c:
        version = c.execute('select value from startup_radar.runtime_settings where key=%s', (OPERATION_KEY,)).fetchone()['value']['version']
    actor = admin(db)
    with db.transaction(actor) as c:
        return c.execute('select public.gfc_radar_admin_set_operation(%s,%s,%s) v', (enabled, version, reason)).fetchone()['v']


def set_visibility(db, mode):
    with db.transaction() as c:
        version = c.execute('select value from startup_radar.runtime_settings where key=%s', (VISIBILITY_KEY,)).fetchone()['value']['version']
    actor = admin(db)
    with db.transaction(actor) as c:
        return c.execute('select public.gfc_radar_admin_set_visibility(%s,%s) v', (mode, version)).fetchone()['v']


def counts(db):
    with db.transaction() as c:
        return {t: c.execute(f'select count(*) n from startup_radar.{t}').fetchone()['n']
                for t in ('ingestion_runs', 'weekly_briefings', 'worker_executions', 'weekly_announcements')}


def audit_actions(db):
    with db.transaction() as c:
        return [r['action'] for r in c.execute('select action from startup_radar.admin_audit order by created_at,id').fetchall()]


def test_default_is_running_and_members_only(db):
    with db.transaction() as c:
        assert operation_state(c)['enabled'] is True and visibility_mode(c) == 'MEMBERS_ONLY'


def test_paused_weekly_run_is_a_no_op_before_any_side_effect(db):
    configure_official_channel(db, chat_id=CHAT)
    db.upsert_source('weekly-k', 'K-Startup', 'KSTARTUP', {}); db.upsert_source('weekly-b', 'BizInfo', 'BIZINFO', {})
    assert set_operation(db, False, 'maintenance')['operation']['enabled'] is False
    before = counts(db)
    collector = Mock(side_effect=AssertionError('Paused run must not collect'))
    transport = delivered_transport()
    result = run_weekly(db, transport, at=AT, collector=collector)
    assert result['status'] == 'PAUSED' and result['reason'] == 'RADAR_OPERATION_PAUSED' and 'execution_id' not in result
    assert not collector.called and not transport.send.called
    assert counts(db) == before  # no ingestion_run, no briefing, no execution, no announcement
    assert audit_actions(db) == ['RADAR_OPERATION_PAUSED', 'RADAR_RUN_SKIPPED_PAUSED']


def test_paused_ingest_and_refresh_jobs_are_skipped_without_a_claim(db):
    set_operation(db, False)
    executor = Mock(side_effect=AssertionError('Paused job must not execute'))
    for kind in ('INGEST', 'REFRESH', 'TICK'):
        result = run_job(db, kind, executor=executor)
        assert result['status'] == 'PAUSED' and result['kind'] == kind
    assert not executor.called and counts(db)['worker_executions'] == 0


def test_resume_allows_the_next_run_but_never_replays_anything_itself(db):
    set_operation(db, False)
    before = counts(db)
    resumed = set_operation(db, True)
    assert resumed['operation']['enabled'] is True and resumed['operation']['version'] == 3
    assert counts(db) == before and 'RADAR_OPERATION_RESUMED' in audit_actions(db)
    # The next normal execution runs as usual (published from the fixture collection).
    acquired = collection(db); db.upsert_source('weekly-b', 'BizInfo', 'BIZINFO', {})
    result = run_weekly(db, at=AT, collector=Mock(return_value=acquired))
    assert result['status'] == 'SUCCESS' and result['published'] and 'execution_id' in result


def test_cli_treats_paused_as_a_successful_exit(monkeypatch, capsys, db):
    set_operation(db, False)
    monkeypatch.setenv('DATABASE_URL', os.environ['TEST_DATABASE_URL'])
    assert cli.main(['weekly']) == 0
    assert '"PAUSED"' in capsys.readouterr().out


def test_operation_audit_records_actor_before_and_after(db):
    set_operation(db, False, 'maintenance window')
    with db.transaction() as c:
        row = c.execute("select actor_id,detail from startup_radar.admin_audit where action='RADAR_OPERATION_PAUSED'").fetchone()
    assert row['actor_id'] is not None
    assert row['detail']['before']['enabled'] is True and row['detail']['after']['enabled'] is False
    assert row['detail']['reason'] == 'maintenance window' and str(row['detail']['after']['updated_by']) == str(row['actor_id'])


def test_private_visibility_suppresses_the_weekly_channel_send(db):
    configure_official_channel(db, chat_id=CHAT)
    result = build_briefing(db, collection(db), AT)
    set_visibility(db, 'PRIVATE')
    transport = delivered_transport()
    assert announce(db, result['briefing_id'], transport)['state'] == 'VISIBILITY_PRIVATE'
    assert not transport.send.called and ledger(db) == []
    for mode in ('MEMBERS_ONLY', 'PUBLIC'):
        set_visibility(db, mode)
        outcome = announce(db, result['briefing_id'], transport)
        assert outcome['state'] == 'RECORDED'
    assert transport.send.call_count == 1  # first allowed mode sends once; the ledger blocks the second


def test_withdrawn_briefing_is_hidden_kept_intact_and_never_newly_announced(db):
    configure_official_channel(db, chat_id=CHAT)
    result = build_briefing(db, collection(db), AT)
    briefing_id = result['briefing_id']
    actor = admin(db)
    with db.transaction() as c:
        before = c.execute('select to_jsonb(b) data from startup_radar.weekly_briefings b where id=%s', (briefing_id,)).fetchone()['data']
        items_before = c.execute('select program_id,program_version_id,change_type,display_order,material_hash,snapshot,stage_codes from startup_radar.weekly_briefing_items where briefing_id=%s order by display_order', (briefing_id,)).fetchall()
    with db.transaction(actor) as c:
        listed = c.execute("select public.gfc_radar_admin_withdraw_briefing(%s,'posted by mistake') v", (briefing_id,)).fetchone()['v']
    assert listed['items'][0]['withdrawn_at'] is not None and listed['items'][0]['announced'] is False
    transport = delivered_transport()
    assert announce(db, briefing_id, transport)['state'] == 'WITHDRAWN' and not transport.send.called and ledger(db) == []
    with db.transaction(actor) as c:
        assert c.execute('select public.gfc_radar_weekly_briefings() v').fetchone()['v']['total'] == 0
        assert c.execute('select public.gfc_radar_weekly_briefing(%s) v', (briefing_id,)).fetchone()['v'] is None
        restored = c.execute('select public.gfc_radar_admin_restore_briefing(%s) v', (briefing_id,)).fetchone()['v']
    assert restored['items'][0]['withdrawn_at'] is None
    with db.transaction() as c:
        after = c.execute('select to_jsonb(b) data from startup_radar.weekly_briefings b where id=%s', (briefing_id,)).fetchone()['data']
        items_after = c.execute('select program_id,program_version_id,change_type,display_order,material_hash,snapshot,stage_codes from startup_radar.weekly_briefing_items where briefing_id=%s order by display_order', (briefing_id,)).fetchall()
    assert after == before and items_after == items_before  # revision, published_at, items, hashes all untouched
    assert audit_actions(db) == ['WEEKLY_BRIEFING_WITHDRAWN', 'WEEKLY_BRIEFING_RESTORED']
    # Restore does not announce by itself; the next normal run may.
    assert ledger(db) == []
    # The withdrawn week stays known history: a rerun of the same week does not treat its programs as new.
    rerun = run_weekly(db, at=AT, collector=Mock(side_effect=AssertionError('Published week must stay stable')))
    assert rerun['briefing_id'] == briefing_id and rerun['unchanged']


def test_member_cannot_pause_change_visibility_or_withdraw(db):
    member = uuid4()
    with db.transaction() as c:
        c.execute('insert into auth.users(id) values(%s)', (member,))
        c.execute("insert into public.test_gfc_roles values(%s,'member')", (member,))
    result = build_briefing(db, collection(db), AT)
    for call, args in (('gfc_radar_admin_set_operation(%s,%s)', (False, 1)), ('gfc_radar_admin_set_visibility(%s,%s)', ('PUBLIC', 1)),
                       ('gfc_radar_admin_withdraw_briefing(%s)', (result['briefing_id'],)), ('gfc_radar_admin_control()', ())):
        with pytest.raises(Exception) as caught:
            with db.transaction(member) as c:
                c.execute(f'select public.{call}', args)
        assert 'GFC admin required' in str(caught.value)
    with db.transaction() as c:
        assert operation_state(c)['enabled'] is True and visibility_mode(c) == 'MEMBERS_ONLY'
        assert c.execute('select withdrawn_at from startup_radar.weekly_briefings').fetchone()['withdrawn_at'] is None
