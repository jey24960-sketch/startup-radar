"""`telegram-channel --verify` prints into public Actions logs: only operator facts may appear."""
import json
from contextlib import contextmanager
from unittest.mock import Mock

import pytest

from radar import cli

STORED = {'enabled': True, 'chat_id': '@gfc_startup_radar', 'name': 'GFC StartupRadar', 'join_url': 'https://t.me/gfc_startup_radar'}
INVITE = 'https://t.me/+VwaipXofhco1MjA9'


class StubDatabase:
    """Just enough of Database for channel_admin: one runtime_settings row, audit inserts collected."""

    def __init__(self, url=None):
        self.audit = []

    @contextmanager
    def transaction(self, user_id=None):
        yield self

    def execute(self, query, params=()):
        if 'admin_audit' in query:
            self.audit.append(params)
        self._query = query
        return self

    def fetchone(self):
        return {'value': STORED, 'updated_at': '2026-09-16'} if 'runtime_settings' in self._query else None


@pytest.fixture
def stubs(monkeypatch):
    transport = Mock()
    transport.get_me.return_value = {'state': 'OK', 'id': 8711845252, 'first_name': 'StartupRadar', 'username': 'radar_bot', 'is_bot': True}
    transport.get_chat.return_value = {'state': 'OK', 'id': -1002961552096, 'title': 'GFC StartupRadar', 'type': 'channel',
                                       'username': 'gfc_startup_radar', 'invite_link': INVITE, 'description': 'desc'}
    transport.get_chat_member.return_value = {'state': 'OK', 'status': 'administrator', 'can_post_messages': True,
                                              'user': {'id': 8711845252, 'username': 'radar_bot'}}
    monkeypatch.setattr(cli, 'Database', StubDatabase)
    monkeypatch.setattr(cli, 'TelegramTransport', lambda token: transport)
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', '8711845252:AAFakeTokenForRedactionTestOnly_x')
    return transport


def test_verify_output_shows_operator_facts_but_no_raw_telegram_payload(stubs, capsys):
    assert cli.main(['telegram-channel', '--verify']) == 0
    out = capsys.readouterr().out
    result = json.loads(out)
    verification = result['verification']
    assert verification['status'] == 'SUCCESS' and verification['reason'] == 'READY'
    assert verification['checks']['bot']['username'] == 'radar_bot'
    assert verification['chat_title'] == 'GFC StartupRadar' and verification['checks']['chat']['type'] == 'channel'
    assert verification['checks']['membership'] == {'state': 'OK', 'status': 'administrator', 'can_post_messages': True}
    assert verification['checks']['chat']['id'] == '-100…2096'
    for leaked in ('invite_link', 't.me/+', 'VwaipXofhco1MjA9', 'description', '8711845252', '-1002961552096', 'AAFakeToken', "'user'"):
        assert leaked not in out, leaked
    assert not stubs.send.called


def test_verify_failure_exits_nonzero_with_an_actionable_reason(stubs, capsys):
    stubs.get_chat.return_value = {'state': 'FAILED', 'error': 'Bad Request: chat not found', 'raw': {'error_code': 400}}
    assert cli.main(['telegram-channel', '--verify']) == 1
    out = capsys.readouterr().out
    verification = json.loads(out)['verification']
    assert verification['status'] == 'FAILED' and verification['reason'] == 'CHAT_NOT_ACCESSIBLE'
    assert verification['checks']['chat'] == {'state': 'FAILED', 'error': 'Bad Request: chat not found'}
    assert 'error_code' not in out and 'AAFakeToken' not in out
