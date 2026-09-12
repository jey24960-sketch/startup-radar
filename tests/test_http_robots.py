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


def test_actual_api_http_400_is_still_a_failure():
    http=client(400)
    http.check_robots=Mock()
    with pytest.raises(SourceFailure) as error:http.get('https://example.org/api')
    assert error.value.kind=='HTTP' and error.value.http_status==400
