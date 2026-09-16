"""Operator-only setup of the official weekly Telegram channel.

One-time setup, then no per-member administration: create the channel, make
the existing StartupRadar bot a posting administrator, store the chat id and
the public join link here, verify read-only, enable. Every write is audited.
Nothing in this module posts the weekly briefing.
"""
from psycopg.types.json import Jsonb
from radar.broadcast import SETTING_KEY, member_view, official_channel, safe_link, verify_channel

TEST_LABEL = '[GFC StartupRadar · 테스트]'


def read_channel(db):
    with db.transaction() as c:
        row = c.execute('select value,updated_at from startup_radar.runtime_settings where key=%s', (SETTING_KEY,)).fetchone()
    value = row['value'] if row else {}
    return {'stored': value, 'usable': official_channel(value) is not None, 'member_view': member_view(value),
            'updated_at': str(row['updated_at']) if row else None}


def configure_channel(db, *, chat_id=None, join_url=None, name=None, enabled=None, note):
    if not note or not 5 <= len(note.strip()) <= 300:
        raise ValueError('An operator note of 5..300 characters is required')
    if join_url not in (None, '') and not safe_link(join_url):
        raise ValueError('join_url must be an https link')
    if chat_id not in (None, '') and not str(chat_id).lstrip('-').isdigit() and not str(chat_id).startswith('@'):
        raise ValueError('chat_id must be a numeric Telegram chat id (channels are usually -100...) or an @username')
    with db.transaction() as c:
        current = c.execute('select value from startup_radar.runtime_settings where key=%s for update', (SETTING_KEY,)).fetchone()
        value = dict((current or {}).get('value') or {})
        before = dict(value)
        if chat_id is not None:
            value['chat_id'] = str(chat_id).strip() or None
        if join_url is not None:
            value['join_url'] = join_url.strip() or None
        if name is not None:
            value['name'] = name.strip() or 'GFC StartupRadar'
        if enabled is not None:
            value['enabled'] = bool(enabled)
        value.setdefault('name', 'GFC StartupRadar')
        value.setdefault('enabled', False)
        if value.get('enabled') and not value.get('chat_id'):
            raise ValueError('Cannot enable the official channel without a chat_id')
        c.execute('insert into startup_radar.runtime_settings(key,value) values(%s,%s) '
                  'on conflict(key) do update set value=excluded.value,updated_at=now()', (SETTING_KEY, Jsonb(value)))
        c.execute("insert into startup_radar.admin_audit(action,entity_id,detail) values('WEEKLY_TELEGRAM_CHANNEL_CONFIGURED',%s,%s)",
                  (SETTING_KEY, Jsonb({'note': note.strip(), 'before': before, 'after': value, 'actor': 'PRIVILEGED_OPERATOR'})))
    return {'status': 'SUCCESS', **read_channel(db)}


def verify(db, transport):
    """Read-only Telegram verification; never sends a message."""
    channel = official_channel(read_channel(db)['stored'])
    if channel is None:
        return {'status': 'FAILED', 'reason': 'NO_BROADCAST_CHANNEL', 'ok': False}
    verdict = verify_channel(transport, channel)
    with db.transaction() as c:
        c.execute("insert into startup_radar.admin_audit(action,entity_id,detail) values('WEEKLY_TELEGRAM_CHANNEL_VERIFIED',%s,%s)",
                  (SETTING_KEY, Jsonb({'ok': verdict['ok'], 'reason': verdict['reason'],
                                       'chat_title': verdict.get('chat_title'), 'telegram_sent': False})))
    return {'status': 'SUCCESS' if verdict['ok'] else 'FAILED', **verdict}


def test_post(db, transport):
    """Explicit, clearly labelled operator test. Not a weekly announcement; not ledgered as one."""
    channel = official_channel(read_channel(db)['stored'])
    if channel is None:
        return {'status': 'FAILED', 'reason': 'NO_BROADCAST_CHANNEL'}
    text = f'{TEST_LABEL}\n\n공식 채널 연결 확인용 테스트 메시지입니다. 주간 공지가 아니며 무시하셔도 됩니다.'
    result = transport.send(channel['chat_id'], text)
    with db.transaction() as c:
        c.execute("insert into startup_radar.admin_audit(action,entity_id,detail) values('WEEKLY_TELEGRAM_CHANNEL_TEST_POST',%s,%s)",
                  (SETTING_KEY, Jsonb({'state': result.get('state'), 'receipt': result.get('receipt'),
                                       'error': result.get('error'), 'test_message': True})))
    return {'status': 'SUCCESS' if result.get('state') == 'DELIVERED' else 'FAILED', **result}
