from datetime import datetime, timedelta
from uuid import uuid4
from unittest.mock import Mock
import pytest
import psycopg
from psycopg.types.json import Jsonb
from core.clock import SEOUL
from radar.weekly import build_briefing, run_weekly, announce
from radar.weekly_schedule import due_at
from test_database import db
from test_weekly import collection, AT


@pytest.fixture
def admin(db):
    user = uuid4()
    with db.transaction() as c:
        c.execute('insert into auth.users(id) values(%s)', (user,))
        c.execute("insert into public.test_gfc_roles values(%s,'admin')", (user,))
        c.execute('truncate startup_radar.weekly_schedule_attempts')
        c.execute('update startup_radar.weekly_schedule set enabled=true,weekday=1,hour=15,minute=0,revision=1')
    return user


def edit(db, actor, bid, revision=1, items=None, note='공식 공고 확인 후 정정'):
    with db.transaction(actor) as c:
        return c.execute('select public.gfc_radar_edit_weekly_briefing(%s,%s,%s,%s,%s,%s) result',
                         (bid, revision, '정정된 주간 공지', '수정 요약', Jsonb(items or []), note)).fetchone()['result']


@pytest.mark.parametrize('role', ['member', 'external'])
def test_non_admin_cannot_edit_or_change_schedule(db, admin, role):
    bid = build_briefing(db, collection(db, 1), AT)['briefing_id']
    user = uuid4()
    with db.transaction() as c:
        c.execute('insert into auth.users(id) values(%s)', (user,))
        c.execute('insert into public.test_gfc_roles values(%s,%s)', (user, role))
    with pytest.raises(psycopg.errors.InsufficientPrivilege): edit(db, user, bid)
    for query in ('select public.gfc_radar_weekly_schedule()',
                  'select public.gfc_radar_save_weekly_schedule(true,4,20,30,1)',
                  "update startup_radar.weekly_schedule set hour=0",
                  "update startup_radar.weekly_briefings set title='bypass'"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with db.transaction(user) as c: c.execute(query)


def test_schedule_save_audit_and_conflict(db, admin):
    with db.transaction(admin) as c:
        value = c.execute('select public.gfc_radar_save_weekly_schedule(true,6,23,45,1) value').fetchone()['value']
        assert (value['weekday'], value['hour'], value['minute'], value['revision']) == (6, 23, 45, 2)
    with pytest.raises(psycopg.errors.SerializationFailure):
        with db.transaction(admin) as c: c.execute('select public.gfc_radar_save_weekly_schedule(false,0,0,0,1)')
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        with db.transaction(admin) as c: c.execute('select public.gfc_radar_save_weekly_schedule(true,7,24,60,2)')
    with db.transaction() as c:
        audit = c.execute("select detail from startup_radar.admin_audit where action='WEEKLY_SCHEDULE_EDIT' and actor_id=%s", (admin,)).fetchone()['detail']
        assert audit['before']['weekday'] == 1 and audit['after']['minute'] == 45


def test_correction_preserves_original_hash_audit_and_rejects_stale_edit(db, admin):
    acquired = collection(db, 1)
    bid = build_briefing(db, acquired, AT)['briefing_id']
    with db.transaction() as c:
        before = c.execute('select * from startup_radar.weekly_briefing_items where briefing_id=%s', (bid,)).fetchone()
    changed = edit(db, admin, bid, items=[{'display_order': 0, 'facts': {'title': '올바른 사업명', 'application_end_at': '2027-01-20T23:59:59+09:00', 'application_end_precision': 'DATE'}}])
    assert changed['revision'] == 2
    with db.transaction(admin) as c:
        view = c.execute('select public.gfc_radar_weekly_briefing(%s) value', (bid,)).fetchone()['value']
        assert view['title'] == '정정된 주간 공지' and view['items'][0]['facts']['title'] == '올바른 사업명'
    with pytest.raises(psycopg.errors.SerializationFailure): edit(db, admin, bid)
    with db.transaction() as c:
        after = c.execute('select * from startup_radar.weekly_briefing_items where briefing_id=%s', (bid,)).fetchone()
        assert after['material_hash'] == before['material_hash']
        assert after['program_version_id'] == before['program_version_id']
        audit = c.execute("select detail from startup_radar.admin_audit where action='WEEKLY_EDITORIAL_CORRECTION' and entity_id=%s", (bid,)).fetchone()['detail']
        assert audit['items_before'][0]['snapshot']['title'] == before['snapshot']['title']
        assert audit['reason'] == '공식 공고 확인 후 정정'
    # Editorial wording must not look like a new official-source change next week.
    assert build_briefing(db, acquired, AT + timedelta(days=7))['item_count'] == 0


@pytest.mark.parametrize('patch', [
    {'official_url': 'javascript:alert(1)'}, {'title': ''}, {'requirements': []},
    {'application_end_at': '2027-01-01'},
    {'application_end_at': None, 'application_end_precision': 'DATE'},
])
def test_invalid_correction_is_atomic(db, admin, patch):
    bid = build_briefing(db, collection(db, 1), AT)['briefing_id']
    with pytest.raises(psycopg.Error): edit(db, admin, bid, items=[{'display_order': 0, 'facts': patch}])
    with db.transaction() as c:
        assert c.execute('select revision from startup_radar.weekly_briefings where id=%s', (bid,)).fetchone()['revision'] == 1


def test_seoul_calendar_boundary_and_one_automatic_attempt(db, admin):
    acquired = collection(db, 1)
    db.upsert_source('weekly-b', 'Biz', 'BIZINFO', {})
    collector = Mock(return_value=acquired)
    due = datetime(2026, 9, 15, 15, 0, tzinfo=SEOUL)
    assert due_at({'weekday': 1, 'hour': 15, 'minute': 0}, due) == due
    result = run_weekly(db, at=due-timedelta(minutes=1), scheduled=True, collector=collector)
    assert not result['executed'] and not collector.called
    result = run_weekly(db, at=due, scheduled=True, collector=collector)
    assert result['published'] and collector.call_count == 1
    with db.transaction(admin) as c: c.execute('select public.gfc_radar_save_weekly_schedule(true,0,0,0,1)')
    assert not run_weekly(db, at=due+timedelta(hours=2), scheduled=True, collector=collector)['executed']
    assert collector.call_count == 1


def test_disabled_and_failed_schedule_never_loops(db, admin):
    due = datetime(2026, 9, 20, 23, 59, tzinfo=SEOUL)
    collector = Mock(side_effect=RuntimeError('fixture failure'))
    with db.transaction(admin) as c: c.execute('select public.gfc_radar_save_weekly_schedule(false,6,23,59,1)')
    assert not run_weekly(db, at=due, scheduled=True, collector=collector)['executed']
    with db.transaction(admin) as c: c.execute('select public.gfc_radar_save_weekly_schedule(true,6,23,59,2)')
    collection(db, 1)
    # weekly requires both registered source types before invoking its collector.
    db.upsert_source('weekly-b', 'Biz', 'BIZINFO', {})
    first = run_weekly(db, at=due, scheduled=True, collector=collector)
    assert first['status'] == 'FAILED' and collector.call_count == 1
    assert not run_weekly(db, at=due, scheduled=True, collector=collector)['executed']
    assert collector.call_count == 1


def test_correction_does_not_resend_delivered_announcement(db, admin):
    bid = build_briefing(db, collection(db, 1), AT)['briefing_id']
    team = db.create_team('fixture', admin)
    with db.transaction() as c:
        c.execute("insert into startup_radar.telegram_subscriptions(team_id,chat_id,enabled,digest_enabled,channel_health) values(%s,'fixture',true,true,'HEALTHY')", (team['id'],))
    transport = Mock(); transport.send.return_value = {'state': 'DELIVERED'}
    announce(db, bid, transport)
    edit(db, admin, bid)
    announce(db, bid, transport)
    assert transport.send.call_count == 1


def test_pending_message_uses_corrected_text_and_sending_blocks_edit(db, admin):
    bid = build_briefing(db, collection(db, 1), AT)['briefing_id']
    team = db.create_team('fixture', admin)
    with db.transaction() as c:
        sub = c.execute("insert into startup_radar.telegram_subscriptions(team_id,chat_id,enabled,digest_enabled,channel_health) values(%s,'fixture',true,true,'HEALTHY') returning id", (team['id'],)).fetchone()['id']
        c.execute("insert into startup_radar.weekly_announcements(briefing_id,subscription_id,chat_id,payload,state) values(%s,%s,'fixture','outdated','SENDING')", (bid, sub))
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState): edit(db, admin, bid)
    with db.transaction() as c:
        c.execute("update startup_radar.weekly_announcements set state='PENDING' where briefing_id=%s", (bid,))
    edit(db, admin, bid)
    transport = Mock(); transport.send.return_value = {'state': 'DELIVERED'}
    announce(db, bid, transport)
    assert '정정된 주간 공지' in transport.send.call_args.args[1]
    assert transport.send.call_count == 1
