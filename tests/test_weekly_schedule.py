"""Delayed scheduler requests share the existing durable worker ownership.

DB cases use only a marked ephemeral database, fake collectors and transports.
"""
import os
import time
from datetime import timedelta
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from radar.executions import claim_execution, finish_execution, weekly_schedule_arguments
from radar.weekly import announce, run_weekly, recover_weekly_announcement, week_window
from radar.cli import main
from test_database import db
from test_weekly import collection, configure_official_channel, AT
from core.clock import now, SEOUL

db_required = pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), reason='Explicit ephemeral database required')
native_required = pytest.mark.skipif(os.environ.get('TEST_NATIVE_POSTGRES') != '1', reason='Native concurrent PostgreSQL required')
# Real scheduled claims intentionally reject early execution. Do not weaken the
# production clock check to run success cases on Monday or early Tuesday in CI.
_clock=now().astimezone(SEOUL)
after_due = pytest.mark.skipif(_clock.weekday()==0 or (_clock.weekday()==1 and _clock.hour<9),
    reason='Positive scheduled-claim cases require the real Seoul-week due time; early claims are intentionally rejected')


def request(db, offset=0):
    with db.transaction() as c:
        week = c.execute("select date_trunc('week',now() at time zone 'Asia/Seoul')::date d").fetchone()['d'] + timedelta(days=offset)
        row = c.execute("insert into startup_radar.weekly_schedule_requests(week_start,scheduled_at) values(%s,(%s::date+interval '1 day 9 hours') at time zone 'Asia/Seoul') returning id", (week, week)).fetchone()
    return row['id'], week


@pytest.mark.parametrize('request_id,week', [(uuid4(), None), (None, '2026-09-21'), (uuid4(), '2026-09-22'), (uuid4(), '20260921'), (uuid4(), 'not-a-date')])
def test_scheduler_arguments_are_an_explicit_iso_monday_pair(request_id, week):
    with pytest.raises(ValueError): weekly_schedule_arguments(request_id, week)


@pytest.mark.parametrize('extra', [['--draft'], ['--revision-note', 'manual correction'], ['--check-sources']])
def test_scheduler_cli_rejects_mutating_manual_modes_before_database_access(monkeypatch, extra):
    database = Mock(side_effect=AssertionError('Invalid input must not connect'))
    monkeypatch.setattr('radar.cli.Database', database)
    with pytest.raises(SystemExit) as error:
        main(['weekly', '--scheduler-request-id', str(uuid4()), '--expected-week-start', '2026-09-21', *extra])
    assert error.value.code == 2 and not database.called


def test_scheduler_cli_forwards_identity_without_changing_manual_options(monkeypatch):
    request_id = uuid4()
    monkeypatch.setattr('radar.cli.Database', Mock())
    runner = Mock(return_value={'status': 'SUCCESS'})
    monkeypatch.setattr('radar.weekly.run_weekly', runner)
    assert main(['weekly', '--scheduler-request-id', str(request_id), '--expected-week-start', '2026-09-21']) == 0
    assert runner.call_args.kwargs['scheduler_request_id'] == request_id
    assert runner.call_args.kwargs['expected_week_start'] == '2026-09-21'


@db_required
def test_stale_future_missing_and_mismatched_requests_do_not_claim_collect_or_send(db):
    past_id, past = request(db, -7)
    future_id, future = request(db, 7)
    collector = Mock(side_effect=AssertionError('No collection'))
    transport = Mock(side_effect=AssertionError('No delivery'))
    for request_id, week, state in [(past_id, past, 'STALE_SCHEDULE_REQUEST'), (future_id, future, 'STALE_SCHEDULE_REQUEST'),
                                   (uuid4(), past, 'INVALID_SCHEDULE_REQUEST'), (past_id, future, 'INVALID_SCHEDULE_REQUEST')]:
        result = run_weekly(db, transport, collector=collector, scheduler_request_id=request_id, expected_week_start=week)
        assert result['state'] == state and result['executed'] is False
        assert 'execution_id' not in result
    with db.transaction() as c:
        assert c.execute('select count(*) n from startup_radar.worker_executions').fetchone()['n'] == 0
        assert c.execute('select count(*) n from startup_radar.weekly_announcements').fetchone()['n'] == 0
    assert not collector.called and not transport.send.called


@db_required
@after_due
def test_scheduled_worker_uses_database_week_and_duplicate_request_is_a_no_op(db):
    request_id, week = request(db)
    acquired = collection(db)
    db.upsert_source('weekly-b', 'BizInfo', 'BIZINFO', {})
    collector = Mock(return_value=acquired)
    first = run_weekly(db, at=AT-timedelta(days=30), collector=collector, scheduler_request_id=request_id, expected_week_start=week)
    assert first['status'] == 'SUCCESS' and first['expected_week_start'] == str(week)
    again = run_weekly(db, collector=Mock(side_effect=AssertionError('Duplicate collection')), scheduler_request_id=request_id, expected_week_start=week)
    assert again['state'] == 'DUPLICATE_SCHEDULE_REQUEST' and 'execution_id' not in again
    assert again['previous_execution_id'] == first['execution_id'] and collector.call_count == 1
    with db.transaction() as c:
        row = c.execute('select id,week_start,revision from startup_radar.weekly_briefings').fetchone()
        assert str(row['id']) == first['briefing_id'] and row['week_start'] == week and row['revision'] == 1
        assert str(c.execute('select execution_id from startup_radar.weekly_schedule_requests where id=%s', (request_id,)).fetchone()['execution_id']) == first['execution_id']
        assert c.execute('select count(*) n from startup_radar.worker_executions').fetchone()['n'] == 1


@db_required
@after_due
def test_lost_scheduler_claim_acknowledgement_cannot_execute_twice(db):
    request_id, week = request(db)
    class LostAcknowledgement:
        @contextmanager
        def transaction(self):
            with db.transaction() as c: yield c
            raise psycopg.OperationalError('Synthetic lost commit acknowledgement')
    collector = Mock(side_effect=AssertionError('Unconfirmed owner must never collect'))
    result = run_weekly(LostAcknowledgement(), collector=collector, scheduler_request_id=request_id, expected_week_start=week)
    assert result['status'] == 'UNCERTAIN' and result['scheduler_request_id'] == str(request_id)
    again = run_weekly(db, collector=collector, scheduler_request_id=request_id, expected_week_start=week)
    assert again['state'] == 'DUPLICATE_SCHEDULE_REQUEST' and not collector.called
    with db.transaction() as c:
        assert c.execute("select count(*) n from startup_radar.worker_executions where state='RUNNING'").fetchone()['n'] == 1


@db_required
@after_due
def test_weekly_finalization_failure_keeps_execution_identity_and_never_releases_owner(db, monkeypatch):
    request_id, week = request(db)
    acquired = collection(db); db.upsert_source('weekly-b', 'BizInfo', 'BIZINFO', {})
    monkeypatch.setattr('radar.executions.finish_execution', Mock(side_effect=psycopg.OperationalError('Synthetic acknowledgement loss')))
    result = run_weekly(db, collector=Mock(return_value=acquired), scheduler_request_id=request_id, expected_week_start=week)
    assert result['status'] == 'UNCERTAIN' and result['execution_id'] and result['scheduler_request_id'] == str(request_id)
    again = run_weekly(db, collector=Mock(side_effect=AssertionError('No retry')), scheduler_request_id=request_id, expected_week_start=week)
    assert again['state'] == 'DUPLICATE_SCHEDULE_REQUEST'
    with db.transaction() as c:
        assert c.execute("select count(*) n from startup_radar.worker_executions where state='RUNNING'").fetchone()['n'] == 1
        assert c.execute('select count(*) n from startup_radar.weekly_briefings').fetchone()['n'] == 1


@db_required
@after_due
def test_paused_scheduler_request_remains_skipped_after_resume(db):
    request_id, week = request(db)
    with db.transaction() as c:
        c.execute("update startup_radar.runtime_settings set value=jsonb_set(value,'{enabled}','false') where key='radar_operation'")
    first = run_weekly(db, scheduler_request_id=request_id, expected_week_start=week)
    assert first['status'] == 'PAUSED'
    with db.transaction() as c:
        assert c.execute('select suppressed_reason from startup_radar.weekly_schedule_requests where id=%s', (request_id,)).fetchone()['suppressed_reason'] == 'OPERATOR_PAUSED'
        c.execute("update startup_radar.runtime_settings set value=jsonb_set(value,'{enabled}','true') where key='radar_operation'")
    again = run_weekly(db, collector=Mock(side_effect=AssertionError('No automatic catchup')), scheduler_request_id=request_id, expected_week_start=week)
    assert again['status'] == 'PAUSED' and again['state'] == 'SKIPPED_PAUSED'
    with db.transaction() as c:
        assert c.execute('select count(*) n from startup_radar.worker_executions').fetchone()['n'] == 0


@db_required
def test_explicit_failed_delivery_recovery_preserves_publication_payload_and_audits_before_retry(db):
    from radar.weekly import build_briefing
    published = build_briefing(db, collection(db), AT); configure_official_channel(db)
    transport = Mock(); transport.send.return_value = {'state': 'FAILED', 'error': 'Telegram rejected request (HTTP 403)'}
    announce(db, published['briefing_id'], transport)
    with db.transaction() as c:
        before = c.execute('select * from startup_radar.weekly_announcements').fetchone()
        publication = c.execute('select to_jsonb(b) v from startup_radar.weekly_briefings b').fetchone()['v']
    with pytest.raises(ValueError, match='Confirm'): recover_weekly_announcement(db, before['id'], 'Verified rejection fixed')
    result = recover_weekly_announcement(db, before['id'], 'Verified Telegram rejection; channel permission fixed', True)
    assert result['state'] == 'PENDING' and result['retry_dispatched'] is False and transport.send.call_count == 1
    with db.transaction() as c:
        after = c.execute('select * from startup_radar.weekly_announcements').fetchone()
        assert after['id'] == before['id'] and after['payload'] == before['payload'] and after['briefing_id'] == before['briefing_id']
        assert c.execute('select to_jsonb(b) v from startup_radar.weekly_briefings b').fetchone()['v'] == publication
        audit = c.execute("select detail from startup_radar.admin_audit where action='WEEKLY_ANNOUNCEMENT_RETRY_AUTHORIZED'").fetchone()['detail']
        assert audit['previous']['state'] == 'FAILED' and '403' in audit['previous']['failure_reason']
    with pytest.raises(ValueError, match='Only FAILED'): recover_weekly_announcement(db, before['id'], 'Do not reauthorize pending', True)
    transport.send.return_value = {'state': 'DELIVERED', 'receipt': {'message_id': 987}}
    announce(db, published['briefing_id'], transport); announce(db, published['briefing_id'], transport)
    assert transport.send.call_count == 2  # one rejection and exactly one successful delivery


@db_required
@pytest.mark.parametrize('state', ['UNCERTAIN', 'SENDING', 'DELIVERED', 'CANCELLED'])
def test_delivery_recovery_never_resets_ambiguous_inflight_or_delivered_state(db, state):
    from radar.weekly import build_briefing
    published = build_briefing(db, collection(db), AT); configure_official_channel(db)
    transport = Mock(); transport.send.return_value = {'state': 'FAILED'}
    announce(db, published['briefing_id'], transport)
    with db.transaction() as c:
        row = c.execute('update startup_radar.weekly_announcements set state=%s returning id', (state,)).fetchone()
    with pytest.raises(ValueError, match='Only FAILED'):
        recover_weekly_announcement(db, row['id'], 'Do not reset ambiguous delivery', True)
    with db.transaction() as c:
        assert c.execute('select state from startup_radar.weekly_announcements').fetchone()['state'] == state
        assert c.execute("select count(*) n from startup_radar.admin_audit where action='WEEKLY_ANNOUNCEMENT_RETRY_AUTHORIZED'").fetchone()['n'] == 0


@db_required
def test_delivered_without_a_receipt_stays_uncertain_and_is_never_resent(db):
    from radar.weekly import build_briefing
    published = build_briefing(db, collection(db), AT); configure_official_channel(db)
    transport = Mock(); transport.send.return_value = {'state': 'DELIVERED'}
    assert announce(db, published['briefing_id'], transport)['states'] == {'UNCERTAIN': 1}
    announce(db, published['briefing_id'], transport)
    assert transport.send.call_count == 1


@db_required
@native_required
@after_due
def test_scheduled_and_manual_weekly_calls_cannot_collect_concurrently(db):
    request_id, week = request(db)
    acquired = collection(db); db.upsert_source('weekly-b', 'BizInfo', 'BIZINFO', {})
    started, release = Event(), Event()
    def collect(*args, **kwargs):
        started.set(); assert release.wait(10)
        return acquired
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(run_weekly, db, collector=collect, scheduler_request_id=request_id, expected_week_start=week)
        assert started.wait(5)
        try:
            duplicate = run_weekly(db, collector=Mock(side_effect=AssertionError('duplicate')), scheduler_request_id=request_id, expected_week_start=week)
            manual = run_weekly(db, collector=Mock(side_effect=AssertionError('manual overlap')))
            assert duplicate['state'] == 'DUPLICATE_SCHEDULE_REQUEST'
            assert manual['status'] == 'FAILED'
        finally: release.set()
        assert first.result(timeout=10)['status'] == 'SUCCESS'
    with db.transaction() as c:
        assert c.execute('select count(*) n from startup_radar.weekly_briefings').fetchone()['n'] == 1


@db_required
@native_required
def test_concurrent_weekly_announcements_send_once_and_keep_publication_id(db):
    from radar.weekly import build_briefing
    published = build_briefing(db, collection(db), AT)
    configure_official_channel(db)
    started, release = Event(), Event()
    transport = Mock()
    def send(*args):
        started.set(); assert release.wait(10)
        return {'state': 'DELIVERED', 'receipt': {'message_id': 123}}
    transport.send.side_effect = send
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(announce, db, published['briefing_id'], transport)
        assert started.wait(5)
        try:
            second = announce(db, published['briefing_id'], transport)
            assert second['planned'] == 0 and second['states'] == {'SENDING': 1}
        finally: release.set()
        assert first.result(timeout=10)['delivered'] == 1
    assert transport.send.call_count == 1
    with db.transaction() as c:
        assert str(c.execute('select id from startup_radar.weekly_briefings').fetchone()['id']) == published['briefing_id']
        assert c.execute('select count(*) n from startup_radar.weekly_announcements').fetchone()['n'] == 1


@contextmanager
def synthetic_dispatch(db):
    """Replace only the ephemeral DB's HTTP function; no network extension."""
    with db.transaction() as c:
        assert c.info.host=='127.0.0.1' and c.info.dbname=='radar_test'
        assert c.execute('select value from public.radar_test_marker').fetchone()['value']=='ephemeral-test-only'
        original=c.execute("select pg_get_functiondef('startup_radar.weekly_dispatch_http(uuid,date)'::regprocedure) f").fetchone()['f']
        setting=c.execute("select value from startup_radar.runtime_settings where key='weekly_scheduler'").fetchone()['value']
        c.execute("create or replace function startup_radar.weekly_dispatch_http(p_id uuid,p_week date) returns bigint language plpgsql security definer set search_path='' as $$begin perform pg_catalog.pg_sleep(0.8); return 4444; end$$")
        c.execute("update startup_radar.runtime_settings set value=value||%s where key='weekly_scheduler'",
                  (Jsonb({'enabled':True,'active_from_week':str(week_window(AT)[0])}),))
    try:yield
    finally:
        with db.transaction() as c:
            c.execute(original)
            c.execute("update startup_radar.runtime_settings set value=%s where key='weekly_scheduler'",(Jsonb(setting),))


@db_required
@native_required
def test_two_native_scheduler_ticks_create_only_one_dispatch_attempt(db):
    reference=AT+timedelta(days=1,hours=1)
    def tick():
        with db.transaction() as c:return c.execute('select startup_radar.weekly_scheduler_tick_at(%s) v',(reference,)).fetchone()['v']
    with synthetic_dispatch(db), ThreadPoolExecutor(max_workers=1) as pool:
        first=pool.submit(tick)
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            with db.transaction() as c:
                sleeping=c.execute("select exists(select 1 from pg_stat_activity where datname='radar_test' and wait_event='PgSleep' and query like 'select startup_radar.weekly_scheduler_tick_at%%') v").fetchone()['v']
            if sleeping:break
            time.sleep(.01)
        assert sleeping, 'First tick must be inside the synthetic HTTP dispatch with the advisory lock held'
        assert tick()['state']=='CLAIM_BUSY'
        assert first.result(timeout=10)['state']=='DISPATCH_PENDING'
        with db.transaction() as c:
            assert c.execute('select count(*) n from startup_radar.weekly_schedule_requests').fetchone()['n']==1
            assert c.execute('select count(*) n from startup_radar.weekly_dispatch_attempts').fetchone()['n']==1


@db_required
@native_required
@after_due
def test_native_tick_cannot_dispatch_while_a_scheduled_claim_is_committing(db):
    request_id,week=request(db)
    held,release=Event(),Event()
    class HoldingCommit:
        @contextmanager
        def transaction(self):
            with db.transaction() as c:
                yield c
                held.set();assert release.wait(10)
    with synthetic_dispatch(db),ThreadPoolExecutor(max_workers=1) as pool:
        claim=pool.submit(claim_execution,HoldingCommit(),'WEEKLY',scheduler_request_id=request_id,expected_week_start=week)
        assert held.wait(5)
        try:
            with db.transaction() as c:
                assert c.execute('select startup_radar.weekly_scheduler_tick_at(now()) v').fetchone()['v']['state']=='CLAIM_BUSY'
        finally:release.set()
        owner=claim.result(timeout=10)
        with db.transaction() as c:
            assert c.execute('select startup_radar.weekly_scheduler_tick_at(now()) v').fetchone()['v']['state']=='RUNNING'
            assert c.execute('select count(*) n from startup_radar.weekly_dispatch_attempts').fetchone()['n']==0
        finish_execution(db,owner['execution_id'],{'status':'SUCCESS','synthetic':True})
