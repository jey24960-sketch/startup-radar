"""Official weekly channel: message contract and configuration. No database."""
from unittest.mock import Mock

import pytest
from radar.broadcast import (MAX_EXAMPLES, announcement_text, member_view, official_channel,
                             verify_channel)

BRIEFING = {'id': '3a9278b5-f486-4a69-b65b-8369f397282c', 'title': '09.08 ~ 09.14 주간 지원사업 공지', 'item_count': 5}


def item(title, end='2026-10-30T23:59:59+09:00', kind='FIXED_DATE'):
    return {'snapshot': {'title': title, 'application_end_at': end, 'deadline_type': kind}}


def test_message_is_short_uses_published_count_and_links_to_the_article():
    items = [item(f'프로그램 {i}') for i in range(5)]
    text = announcement_text(BRIEFING, items)
    assert text.startswith('[GFC StartupRadar]')
    assert '이번 주 새로 확인·변경 지원사업: 5건' in text
    assert text.count('•') == MAX_EXAMPLES == 3
    assert '프로그램 0' in text and '프로그램 2' in text and '프로그램 3' not in text
    assert '주간 지원사업 전체 보기' in text
    assert 'https://www.gfc-startup.com/notice/weekly/3a9278b5-f486-4a69-b65b-8369f397282c' in text
    # The article is the detail view; the message never dumps bodies.
    assert len(text) < 900


def test_examples_follow_published_order_so_relevant_precede_conditional():
    items = [item('첫째 · GFC_RELEVANT'), item('둘째 · GFC_RELEVANT'), item('셋째 · CONDITIONAL'), item('넷째 · CONDITIONAL')]
    text = announcement_text(BRIEFING, items)
    assert text.index('첫째') < text.index('둘째') < text.index('셋째')
    assert '넷째' not in text


def test_deadline_rendering_respects_date_precision_and_ongoing_acceptance():
    text = announcement_text(BRIEFING, [item('고정 마감'), item('상시', end=None, kind='ROLLING')])
    assert '고정 마감 / 마감: 2026-10-30' in text
    assert '23:59' not in text
    assert '상시 / 마감: 상시 모집' in text


def test_zero_item_week_sends_a_concise_notice_not_invented_items():
    text = announcement_text({**BRIEFING, 'item_count': 0}, [])
    assert '이번 주 새로 확인된 지원사업이 없습니다.' in text
    assert '•' not in text
    assert '/notice/weekly/' in text


def test_html_is_escaped_in_titles():
    text = announcement_text(BRIEFING, [item('<b>주입</b> & 테스트')])
    assert '<b>' not in text and '&lt;b&gt;' in text and '&amp;' in text


@pytest.mark.parametrize('value', [None, {}, {'enabled': False, 'chat_id': '-100', 'join_url': 'https://t.me/x'},
                                   {'enabled': True, 'chat_id': ''}, {'enabled': True, 'chat_id': None}])
def test_missing_disabled_or_blank_channel_means_no_broadcast(value):
    assert official_channel(value) is None
    assert member_view(value)['enabled'] is False and member_view(value)['join_url'] is None


def test_configured_channel_exposes_only_member_safe_fields():
    value = {'enabled': True, 'chat_id': '-1001234567890', 'name': 'GFC StartupRadar', 'join_url': 'https://t.me/gfc_radar'}
    assert official_channel(value)['chat_id'] == '-1001234567890'
    view = member_view(value)
    assert view == {'enabled': True, 'name': 'GFC StartupRadar', 'join_url': 'https://t.me/gfc_radar'}
    assert 'chat_id' not in view


def test_channel_without_a_safe_join_link_is_usable_by_the_worker_but_unavailable_to_members():
    value = {'enabled': True, 'chat_id': '-100', 'join_url': 'http://insecure.example'}
    assert official_channel(value) is not None
    assert member_view(value)['enabled'] is False


def transport(me=None, chat=None, member=None):
    t = Mock()
    t.get_me.return_value = me or {'state': 'OK', 'id': 42, 'username': 'radar_bot'}
    t.get_chat.return_value = chat or {'state': 'OK', 'type': 'channel', 'title': 'GFC StartupRadar'}
    t.get_chat_member.return_value = member or {'state': 'OK', 'status': 'administrator', 'can_post_messages': True}
    return t


def test_verification_is_read_only_and_passes_for_a_posting_admin_bot():
    t = transport()
    verdict = verify_channel(t, {'chat_id': '-100', 'name': 'x'})
    assert verdict['ok'] and verdict['reason'] == 'READY' and verdict['chat_title'] == 'GFC StartupRadar'
    assert not t.send.called


@pytest.mark.parametrize('override,reason', [
    ({'me': {'state': 'FAILED'}}, 'BOT_TOKEN_INVALID'),
    ({'chat': {'state': 'FAILED'}}, 'CHAT_NOT_ACCESSIBLE'),
    ({'chat': {'state': 'OK', 'type': 'group'}}, 'NOT_A_CHANNEL'),
    ({'member': {'state': 'OK', 'status': 'member'}}, 'BOT_NOT_ADMIN'),
    ({'member': {'state': 'OK', 'status': 'administrator', 'can_post_messages': False}}, 'BOT_CANNOT_POST'),
])
def test_verification_names_the_exact_setup_problem(override, reason):
    verdict = verify_channel(transport(**override), {'chat_id': '-100', 'name': 'x'})
    assert not verdict['ok'] and verdict['reason'] == reason
