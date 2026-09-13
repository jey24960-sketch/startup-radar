from unittest.mock import MagicMock,Mock
import pytest
from radar.http import SafeHttp
from radar.adapters.base import SourceFailure


def client(status):
    http=SafeHttp(['example.org'])
    http.validate_url=Mock()
    response=MagicMock()
    response.__enter__.return_value=response
    response.status_code=status
    response.headers={}
    http.session.get=Mock(return_value=response)
    return http


@pytest.mark.parametrize('status',[400,404,410])
def test_unavailable_robots_does_not_claim_publisher_prohibited_collection(status):
    http=client(status)
    http.check_robots('https://example.org/api')
    assert http.robots['https://example.org'] is None
    http.session.get.assert_called_once()
    assert http.session.get.call_args.args[0]=='https://example.org/robots.txt'


@pytest.mark.parametrize('status',[401,403,429,500,503])
def test_access_denial_throttle_or_server_failure_still_blocks(status):
    http=client(status)
    with pytest.raises(SourceFailure,match='ROBOTS_UNAVAILABLE'):
        http.check_robots('https://example.org/api')
    assert 'https://example.org' not in http.robots


def test_explicit_disallow_is_still_enforced():
    http=SafeHttp(['example.org'])
    http._request=Mock(return_value=(b'User-agent: *\nDisallow: /api','text/plain','https://example.org/robots.txt'))
    with pytest.raises(SourceFailure,match='ROBOTS_DENIED'):http.check_robots('https://example.org/api')


def test_robots_rate_limit_is_not_retried():
    http=client(429)
    with pytest.raises(SourceFailure,match='ROBOTS_UNAVAILABLE'):http.get('https://example.org/api')
    assert http.session.get.call_count==1


def test_actual_api_http_400_is_still_a_failure():
    http=client(400)
    http.check_robots=Mock()
    with pytest.raises(SourceFailure) as error:http.get('https://example.org/api')
    assert error.value.kind=='HTTP' and error.value.http_status==400


def test_one_transient_retry_can_recover_without_bypassing_guards(monkeypatch):
    monkeypatch.setattr('radar.http.time.sleep',Mock())
    http=SafeHttp(['example.org']);expected=(b'official','text/plain','https://example.org/api')
    http._request=Mock(side_effect=[SourceFailure('ROBOTS_UNAVAILABLE','Temporary timeout',True),expected])
    assert http.get('https://example.org/api',{'page':1})==expected
    assert http._request.call_count==2
    assert all(call.args==('https://example.org/api',{'page':1}) for call in http._request.call_args_list)


@pytest.mark.parametrize('kind,retryable,attempts',[('TIMEOUT',True,2),('HTTP',True,2),('BLOCKED',False,1),('ROBOTS_DENIED',False,1),('RATE_LIMIT',True,1)])
def test_persistent_failure_is_bounded_and_keeps_its_type(monkeypatch,kind,retryable,attempts):
    monkeypatch.setattr('radar.http.time.sleep',Mock())
    http=SafeHttp(['example.org']);http._request=Mock(side_effect=SourceFailure(kind,'retained failure',retryable))
    with pytest.raises(SourceFailure) as error:http.get('https://example.org/api')
    assert error.value.kind==kind and http._request.call_count==attempts
