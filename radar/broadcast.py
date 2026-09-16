"""The one official GFC Telegram channel that carries every weekly briefing.

Members join the channel once. The worker posts one short summary per
published WEEKLY briefing, built strictly from that briefing's already
published items, and links to the member-only article for detail. Nothing in
this module selects or filters opportunities: what the website shows is what
Telegram summarises, no more and no less.

Per-member and per-team Telegram subscriptions still exist for advanced
alerts and history, but the normal weekly publication no longer depends on
them. This module has no database dependency so the message contract can be
unit-tested anywhere.
"""
import html
import os
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from radar.stage import telegram_tag

SETTING_KEY = 'weekly_telegram_channel'
MAX_EXAMPLES = 3
ONGOING_DEADLINE_TYPES = ('ROLLING', 'UNTIL_BUDGET_EXHAUSTED')
FALLBACK = '공식 공고 확인 필요'


def safe_link(url):
    # Same contract as notifications.safe_link, kept here so this module stays
    # importable without a database driver.
    try:
        parsed = urlsplit(url)
        return bool(parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password
                    and (parsed.port is None or 1 <= parsed.port <= 65535))
    except (ValueError, TypeError):
        return False


def briefing_url(briefing_id):
    base = os.environ.get('RADAR_MEMBER_NOTICE_URL', 'https://www.gfc-startup.com/notice')
    parts = urlsplit(base)
    if not safe_link(base) or parts.query or parts.fragment:
        raise ValueError('Invalid member notice base URL')
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip('/') + '/weekly/' + str(UUID(str(briefing_id))), '', ''))


def official_channel(value):
    """Normalize the stored runtime setting; None means "no broadcast channel".

    Only a fully configured, explicitly enabled channel is usable. A missing
    row, a disabled flag or a blank chat_id all mean the same honest no-op.
    """
    if not isinstance(value, dict) or not value.get('enabled'):
        return None
    chat_id = str(value.get('chat_id') or '').strip()
    if not chat_id:
        return None
    join_url = value.get('join_url')
    return {'chat_id': chat_id, 'name': str(value.get('name') or 'GFC StartupRadar'),
            'join_url': join_url if safe_link(join_url) else None}


def member_view(value):
    """The only fields a verified member may see. chat_id never leaves the server."""
    channel = official_channel(value)
    if channel is None:
        return {'enabled': False, 'name': str((value or {}).get('name') or 'GFC StartupRadar') if isinstance(value, dict) else 'GFC StartupRadar', 'join_url': None}
    return {'enabled': channel['join_url'] is not None, 'name': channel['name'], 'join_url': channel['join_url']}


def _deadline(facts):
    end = facts.get('application_end_at')
    if end:
        return str(end)[:10]
    if facts.get('deadline_type') in ONGOING_DEADLINE_TYPES:
        return '상시 모집'
    return FALLBACK


def announcement_text(briefing, items):
    """Short discovery message; the article is the detail view.

    `items` must be the published weekly_briefing_items in display order, so
    GFC_RELEVANT examples naturally come before CONDITIONAL ones and nothing
    that the website withheld can appear here.
    """
    link = html.escape(briefing_url(briefing['id']), quote=True)
    count = int(briefing.get('item_count') or 0)
    lines = ['[GFC StartupRadar]', '', html.escape(briefing['title']) + '가 게시되었습니다.', '']
    if count == 0 or not items:
        lines.append('이번 주 새로 확인된 지원사업이 없습니다.')
    else:
        lines.append(f'이번 주 새로 확인·변경 지원사업: {count}건')
        lines.append('')
        for item in items[:MAX_EXAMPLES]:
            facts = item['snapshot']
            # Stage comes from the published item, the same stored decision the website shows.
            tag = telegram_tag(item.get('stage_codes'))
            lines.append(html.escape(f"• {tag + ' ' if tag else ''}{str(facts.get('title') or FALLBACK)[:100]} / 마감: {_deadline(facts)}"))
    lines += ['', '주간 지원사업 전체 보기', f'<a href="{link}">{link}</a>']
    return '\n'.join(lines)


def verify_channel(transport, channel):
    """Read-only Telegram checks: the chat exists and the bot may post there.

    Never sends a message. Returns a structured verdict the operator can act on.
    """
    checks = {}
    me = transport.get_me()
    checks['bot'] = me
    if me.get('state') != 'OK':
        return {'ok': False, 'reason': 'BOT_TOKEN_INVALID', 'checks': checks}
    chat = transport.get_chat(channel['chat_id'])
    checks['chat'] = chat
    if chat.get('state') != 'OK':
        return {'ok': False, 'reason': 'CHAT_NOT_ACCESSIBLE', 'checks': checks}
    if chat.get('type') != 'channel':
        return {'ok': False, 'reason': 'NOT_A_CHANNEL', 'checks': checks}
    member = transport.get_chat_member(channel['chat_id'], me['id'])
    checks['membership'] = member
    if member.get('state') != 'OK':
        return {'ok': False, 'reason': 'BOT_MEMBERSHIP_UNKNOWN', 'checks': checks}
    if member.get('status') not in ('administrator', 'creator'):
        return {'ok': False, 'reason': 'BOT_NOT_ADMIN', 'checks': checks}
    if member.get('status') == 'administrator' and member.get('can_post_messages') is False:
        return {'ok': False, 'reason': 'BOT_CANNOT_POST', 'checks': checks}
    return {'ok': True, 'reason': 'READY', 'checks': checks, 'chat_title': chat.get('title')}
