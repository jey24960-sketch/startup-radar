"""Weekly delivery to the ONE official GFC Telegram channel. Needs TEST_DATABASE_URL."""
import os
from datetime import datetime
from unittest.mock import Mock
from uuid import uuid4

import psycopg
import pytest
from core.clock import SEOUL
from radar.weekly import build_briefing, announce, run_weekly
from radar import channel_admin
from test_database import db  # noqa: F401
from test_weekly import collection, configure_official_channel

pytestmark = pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), reason='Explicit test database required')
AT = datetime(2026, 9, 15, 15, tzinfo=SEOUL)
CHAT = '-1001234567890'


def delivered_transport(state='DELIVERED'):
    t = Mock()
    t.send.return_value = {'state': state, 'receipt': {'message_id': 7} if state == 'DELIVERED' else None,
                           'error': None if state == 'DELIVERED' else 'boom'}
    return t


def ledger(db):
    with db.transaction() as c:
        return c.execute('select target_kind,subscription_id,chat_id,state,failure_reason from startup_radar.weekly_announcements order by created_at').fetchall()


def test_published_weekly_with_enabled_channel_plans_exactly_one_message_and_reruns_never_duplicate(db):
    result = build_briefing(db, collection(db), AT)
    configure_official_channel(db, chat_id=CHAT)
    transport = delivered_transport()
    first = announce(db, result['briefing_id'], transport)
    again = announce(db, result['briefing_id'], transport)
    assert first['state'] == 'RECORDED' and first['planned'] == 1 and first['delivered'] == 1
    assert again['planned'] == 0 and transport.send.call_count == 1
    rows = ledger(db)
    assert len(rows) == 1 and rows[0]['target_kind'] == 'OFFICIAL_CHANNEL' and rows[0]['subscription_id'] is None
    assert rows[0]['chat_id'] == CHAT and rows[0]['state'] == 'DELIVERED'
    assert transport.send.call_args.args[0] == CHAT


def test_initial_baseline_never_broadcasts_even_with_channel_enabled(db):
    configure_official_channel(db, chat_id=CHAT)
    result = build_briefing(db, collection(db), AT)
    with db.transaction() as c:
        c.execute("update startup_radar.weekly_briefings set publication_kind='INITIAL_BASELINE',snapshot_date=%s where id=%s",
                  (AT.date(), result['briefing_id']))
    transport = delivered_transport()
    assert announce(db, result['briefing_id'], transport)['state'] == 'BASELINE_ARCHIVE'
    assert not transport.send.called and ledger(db) == []


def test_no_configured_channel_is_an_honest_no_op_not_a_failure(db):
    result = build_briefing(db, collection(db), AT)
    transport = delivered_transport()
    assert announce(db, result['briefing_id'], transport)['state'] == 'NO_BROADCAST_CHANNEL'
    configure_official_channel(db, chat_id=CHAT, enabled=False)
    assert announce(db, result['briefing_id'], transport)['state'] == 'NO_BROADCAST_CHANNEL'
    assert not transport.send.called and ledger(db) == []
    # The weekly run itself is still a success: publication is not blocked by delivery.
    weekly = run_weekly(db, at=AT, collector=Mock(side_effect=AssertionError('no recollection')))
    assert weekly['status'] == 'SUCCESS' and weekly['announcement']['state'] == 'NO_BROADCAST_CHANNEL'


def test_global_delivery_disabled_makes_no_transport_call_and_no_ledger_row(db):
    result = build_briefing(db, collection(db), AT)
    configure_official_channel(db, chat_id=CHAT)
    assert announce(db, result['briefing_id'], None)['state'] == 'DELIVERY_DISABLED'
    assert ledger(db) == []


@pytest.mark.parametrize('state', ['UNCERTAIN', 'FAILED'])
def test_uncertain_or_failed_delivery_is_recorded_and_never_blindly_resent(db, state):
    result = build_briefing(db, collection(db), AT)
    configure_official_channel(db, chat_id=CHAT)
    transport = delivered_transport(state)
    first = announce(db, result['briefing_id'], transport)
    assert first['states'] == {state: 1}
    # A retry with a now-healthy transport must not send again without operator recovery.
    healthy = delivered_transport()
    again = announce(db, result['briefing_id'], healthy)
    assert again['planned'] == 0 and not healthy.send.called
    rows = ledger(db)
    assert rows[0]['state'] == state and rows[0]['failure_reason'].startswith('TELEGRAM_' + state)


def test_transport_exception_is_uncertain_not_lost(db):
    result = build_briefing(db, collection(db), AT)
    configure_official_channel(db, chat_id=CHAT)
    transport = Mock(); transport.send.side_effect = RuntimeError('socket')
    assert announce(db, result['briefing_id'], transport)['states'] == {'UNCERTAIN': 1}


def test_message_reflects_only_the_published_items(db):
    # 5 relevant programs published; only 3 examples, count 5, all from the article.
    result = build_briefing(db, collection(db, 5), AT)
    configure_official_channel(db, chat_id=CHAT)
    transport = delivered_transport()
    announce(db, result['briefing_id'], transport)
    text = transport.send.call_args.args[1]
    assert '이번 주 새로 확인·변경 지원사업: 5건' in text and text.count('•') == 3
    with db.transaction() as c:
        published = [r['t'] for r in c.execute("select snapshot->>'title' t from startup_radar.weekly_briefing_items where briefing_id=%s order by display_order",
                                               (result['briefing_id'],)).fetchall()]
    assert all(t in text for t in published[:3]) and all(t not in text for t in published[3:])


def test_hidden_programs_can_never_reach_telegram(db):
    from test_weekly_publication_filters import acquire, program, NOISE, RELEVANT
    from datetime import timedelta
    result = build_briefing(db, acquire(db,
        program(NOISE, url='https://example.org/noise'),                                   # OUT_OF_SCOPE
        program(RELEVANT + ' 임박', end=AT + timedelta(hours=10), url='https://example.org/near'),  # NEAR_DEADLINE
        program(RELEVANT, url='https://example.org/ok')), AT)
    assert result['item_count'] == 1
    configure_official_channel(db, chat_id=CHAT)
    transport = delivered_transport()
    announce(db, result['briefing_id'], transport)
    text = transport.send.call_args.args[1]
    assert '1건' in text and RELEVANT in text and '카드수수료' not in text and '임박' not in text


def test_team_subscriptions_are_not_consulted_for_the_weekly_broadcast(db):
    result = build_briefing(db, collection(db), AT)
    user = uuid4()
    with db.transaction() as c:
        c.execute('insert into auth.users(id) values(%s)', (user,))
    team = db.create_team('Legacy team', user)
    with db.transaction() as c:
        c.execute("insert into startup_radar.telegram_subscriptions(team_id,chat_id,enabled,digest_enabled,channel_health) values(%s,'legacy-chat',true,true,'HEALTHY')", (team['id'],))
    configure_official_channel(db, chat_id=CHAT)
    transport = delivered_transport()
    announce(db, result['briefing_id'], transport)
    assert transport.send.call_count == 1 and transport.send.call_args.args[0] == CHAT
    # Legacy rows are untouched and still present for advanced features.
    with db.transaction() as c:
        assert c.execute('select count(*) n from startup_radar.telegram_subscriptions').fetchone()['n'] == 1


def test_member_can_read_join_information_but_never_the_chat_id(db):
    configure_official_channel(db, chat_id=CHAT, join_url='https://t.me/gfc_startupradar', name='GFC StartupRadar')
    member, external = uuid4(), uuid4()
    with db.transaction() as c:
        c.execute('insert into auth.users(id) values(%s),(%s)', (member, external))
        c.execute("insert into public.test_gfc_roles values(%s,'member'),(%s,'external')", (member, external))
    with db.transaction(member) as c:
        view = c.execute('select public.gfc_radar_telegram_channel() v').fetchone()['v']
    assert view == {'enabled': True, 'name': 'GFC StartupRadar', 'join_url': 'https://t.me/gfc_startupradar'}
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with db.transaction(external) as c:
            c.execute('select public.gfc_radar_telegram_channel()')
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with db.transaction() as c:
            c.execute('set local role anon'); c.execute('select public.gfc_radar_telegram_channel()')
    # Members cannot read the raw setting row, so chat_id stays server-side.
    with db.transaction(member) as c:
        assert c.execute("select count(*) n from startup_radar.runtime_settings where key='weekly_telegram_channel'").fetchone()['n'] == 0


def test_disabled_channel_renders_as_unavailable_to_members(db):
    configure_official_channel(db, chat_id=CHAT, enabled=False)
    member = uuid4()
    with db.transaction() as c:
        c.execute('insert into auth.users(id) values(%s)', (member,))
        c.execute("insert into public.test_gfc_roles values(%s,'member')", (member,))
    with db.transaction(member) as c:
        view = c.execute('select public.gfc_radar_telegram_channel() v').fetchone()['v']
    assert view['enabled'] is False and view['join_url'] is None


def test_operator_configuration_is_audited_and_validated(db):
    with pytest.raises(ValueError):
        channel_admin.configure_channel(db, chat_id=CHAT, enabled=True, note='x')
    with pytest.raises(ValueError):
        channel_admin.configure_channel(db, join_url='http://insecure', note='insecure link')
    with pytest.raises(ValueError):
        channel_admin.configure_channel(db, enabled=True, note='enable without chat id')
    out = channel_admin.configure_channel(db, chat_id=CHAT, join_url='https://t.me/gfc', enabled=True, note='initial setup')
    assert out['usable'] and out['member_view']['join_url'] == 'https://t.me/gfc'
    with db.transaction() as c:
        audit = c.execute("select detail from startup_radar.admin_audit where action='WEEKLY_TELEGRAM_CHANNEL_CONFIGURED' order by created_at desc limit 1").fetchone()['detail']
    assert audit['after']['chat_id'] == CHAT and audit['note'] == 'initial setup'


def test_verify_is_read_only_and_test_post_is_labelled_and_not_a_weekly_announcement(db):
    channel_admin.configure_channel(db, chat_id=CHAT, enabled=True, note='setup for verification')
    transport = Mock()
    transport.get_me.return_value = {'state': 'OK', 'id': 1}
    transport.get_chat.return_value = {'state': 'OK', 'type': 'channel', 'title': 'GFC StartupRadar'}
    transport.get_chat_member.return_value = {'state': 'OK', 'status': 'administrator', 'can_post_messages': True}
    assert channel_admin.verify(db, transport)['ok'] and not transport.send.called
    transport.send.return_value = {'state': 'DELIVERED', 'receipt': {'message_id': 1}}
    out = channel_admin.test_post(db, transport)
    assert out['status'] == 'SUCCESS' and transport.send.call_args.args[1].startswith('[GFC StartupRadar · 테스트]')
    assert ledger(db) == []


def test_telegram_uses_the_stage_stored_on_the_published_item_not_a_second_classifier(db):
    result = build_briefing(db, collection(db, 2), AT)
    with db.transaction() as c:
        # Whatever the website shows is what Telegram must say, even if it was corrected by hand.
        c.execute("update startup_radar.weekly_briefing_items set stage_codes='{STAGE_3,STAGE_4}' where briefing_id=%s and display_order=0", (result['briefing_id'],))
        c.execute("update startup_radar.weekly_briefing_items set stage_codes='{}' where briefing_id=%s and display_order=1", (result['briefing_id'],))
    configure_official_channel(db, chat_id=CHAT)
    transport = delivered_transport()
    announce(db, result['briefing_id'], transport)
    text = transport.send.call_args.args[1]
    assert '• [MVP·PoC / 사업자·법인 이후] 예비창업자 액셀러레이팅 프로그램 0' in text
    assert '• 예비창업자 액셀러레이팅 프로그램 1 /' in text
    assert 'STAGE_' not in text
    # Adding stage metadata never creates a second delivery.
    announce(db, result['briefing_id'], transport)
    assert transport.send.call_count == 1
