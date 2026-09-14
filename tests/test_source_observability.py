from unittest.mock import Mock
import requests
import pytest
from radar.adapters.base import SourceFailure
from radar.http import SafeHttp
from test_http_robots import client


@pytest.mark.parametrize('error,reason',[
    (requests.ConnectTimeout('PRIVATE_KEY'), 'CONNECT_TIMEOUT'),
    (requests.ReadTimeout('PRIVATE_KEY'), 'READ_TIMEOUT'),
    (requests.exceptions.SSLError('PRIVATE_KEY'), 'TLS_ERROR'),
    (requests.ConnectionError('PRIVATE_KEY'), 'NETWORK_ERROR'),
])
def test_sanitized_root_cause_retains_network_phase(error,reason):
    http=SafeHttp(['example.org']);http.validate_url=Mock();http.check_robots=Mock()
    http.session.get=Mock(side_effect=error)
    with pytest.raises(SourceFailure) as exc:http._request('https://example.org/api?key=PRIVATE_KEY')
    record=exc.value.record(url='https://user:PRIVATE_KEY@example.org/api?key=PRIVATE_KEY#PRIVATE_KEY')
    assert record['reason_code']==reason and 'PRIVATE_KEY' not in str(record)
    assert record['url']=='https://example.org/api'


@pytest.mark.parametrize('error,reason,cause',[
    (SourceFailure('DNS','DNS lookup failed',True),'DNS_ERROR','DNS_ERROR'),
    (SourceFailure('TIMEOUT','Read timed out',True,reason_code='READ_TIMEOUT'),'ROBOTS_FETCH_TIMEOUT','READ_TIMEOUT'),
    (SourceFailure('HTTP','Server unavailable',True,503),'ROBOTS_HTTP_ERROR','HTTP_5XX'),
    (SourceFailure('BLOCKED','Denied',False,403),'ROBOTS_HTTP_ERROR','HTTP_4XX'),
])
def test_robots_failure_keeps_root_cause_and_retry_policy(error,reason,cause):
    http=SafeHttp(['example.org']);http._request=Mock(side_effect=error)
    with pytest.raises(SourceFailure) as exc:http.check_robots('https://example.org/api')
    value=exc.value.record()
    assert value['reason_code']==reason and value['cause_kind']==cause
    assert value['retryable']==error.retryable
    assert value.get('http_status')==error.http_status


def test_invalid_redirect_and_oversize_response_are_explicit():
    http=client(302);http.check_robots=Mock()
    with pytest.raises(SourceFailure,match='INVALID_REDIRECT'):http._request('https://example.org/api')
    http=client(200);http.check_robots=Mock()
    http.session.get.return_value.headers={'Content-Length':'20000001'}
    with pytest.raises(SourceFailure) as exc:http._request('https://example.org/api')
    assert exc.value.record()['reason_code']=='RESPONSE_TOO_LARGE'


def test_invalid_url_cannot_break_error_reporting_or_leak_credentials():
    record=SourceFailure('INVALID_URL','Invalid source URL').record(url='https://[PRIVATE_KEY')
    assert record['url']=='[invalid URL]' and 'PRIVATE_KEY' not in str(record)
