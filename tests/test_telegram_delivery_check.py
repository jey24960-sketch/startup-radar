from unittest.mock import Mock
import pytest
from tools.telegram_delivery_check import check


def environment():
    return {'GITHUB_RUN_ATTEMPT':'1','GITHUB_EVENT_NAME':'workflow_dispatch',
            'TELEGRAM_BOT_TOKEN':'fixture-token','TELEGRAM_CHAT_ID':'-123','GITHUB_RUN_ID':'42'}


@pytest.mark.parametrize('change',[{'GITHUB_RUN_ATTEMPT':'2'},{'GITHUB_EVENT_NAME':'pull_request'},
                                  {'TELEGRAM_CHAT_ID':''},{'TELEGRAM_CHAT_ID':'123,456'},{'TELEGRAM_BOT_TOKEN':''}])
def test_unapproved_context_or_invalid_target_never_sends(change):
    factory=Mock()
    assert check({**environment(),**change},factory)['state']=='NOT_SENT'
    factory.assert_not_called()


@pytest.mark.parametrize('state',['DELIVERED','FAILED','UNCERTAIN'])
def test_one_send_uses_only_configured_recipient_and_does_not_retry(state):
    factory=Mock()
    factory.return_value.send.return_value={'state':state,'receipt':{'message_id':12}}
    result=check(environment(),factory)
    factory.return_value.send.assert_called_once()
    assert factory.return_value.send.call_args.args[0]=='-123'
    assert result['state']==state and result['automatic_retry'] is False
    assert '-123' not in str(result) and 'fixture-token' not in str(result)
