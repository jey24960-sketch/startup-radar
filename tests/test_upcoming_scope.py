import json
from datetime import datetime
from types import SimpleNamespace
import pytest

from core.clock import SEOUL
from radar.adapters.base import SourceFailure
from radar.adapters.official import KStartupApiAdapter


def adapter(monkeypatch, future, nested=False):
    monkeypatch.setenv('KSTARTUP_API_KEY', 'fixture-key')
    monkeypatch.setattr('radar.adapters.official.now', lambda: datetime(2026, 10, 27, tzinfo=SEOUL))
    calls = []
    def get(url, params):
        calls.append(params)
        if 'cond[pbanc_rcpt_bgng_dt::GTE]' in params:
            rows = future
        else:
            rows = [{'pbanc_sn': 1, 'biz_pbanc_nm': '현재 창업 모집',
                     'detl_pg_url': 'https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=1',
                     'pbanc_rcpt_bgng_dt': '20261001'}]
        return json.dumps({'data': {'data': rows} if nested else rows,
                           'matchCount': len(rows)}).encode(), 'application/json', url
    source = {'slug': 'kstartup', 'name': 'KStartup', 'config': {
        'scope': 'OPEN', 'page_size': 100, 'max_pages': 10,
        'include_upcoming_announcements': True}}
    return KStartupApiAdapter(source, SimpleNamespace(get=get)), calls


def test_documented_date_scope_finds_future_notice_outside_recent_pages(monkeypatch):
    a, calls = adapter(monkeypatch, [{'pbanc_sn': 999, 'biz_pbanc_nm': '예비창업자 사전 모집',
        'detl_pg_url': 'https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=999',
        'pbanc_rcpt_bgng_dt': '20261101'}])
    assert [x.source_program_id for x in a.discover()] == ['1', '999']
    assert calls[-1]['cond[pbanc_rcpt_bgng_dt::GTE]'] == '20261027'
    assert 'cond[rcrt_prgs_yn::EQ]' not in calls[-1]
    assert a.pagination.report()['scope_completed']


@pytest.mark.parametrize('nested', [False, True])
def test_ignored_server_filter_is_visible_incomplete_scope(monkeypatch, nested):
    a, _ = adapter(monkeypatch, [{'pbanc_sn': 5, 'biz_pbanc_nm': '지난 공고',
        'pbanc_rcpt_bgng_dt': '20261001'}], nested=nested)
    with pytest.raises(SourceFailure, match='API_SCOPE'):
        list(a.discover())
    assert not a.pagination.report()['scope_completed']


def test_empty_future_scope_is_completed_not_a_source_failure(monkeypatch):
    a, _ = adapter(monkeypatch, [])
    assert len(list(a.discover())) == 1
    assert a.pagination.report()['scope_completed']
