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


def notice(identifier, start):
    return {'pbanc_sn': identifier, 'biz_pbanc_nm': f'창업 지원 모집 {identifier}',
            'biz_aply_url': f'https://example.org/{identifier}', 'pbanc_rcpt_bgng_dt': start}


def test_ignored_filter_salvages_valid_rows_and_bounded_fallback_beyond_recent_window(monkeypatch):
    monkeypatch.setenv('KSTARTUP_API_KEY', 'fixture-key')
    monkeypatch.setattr('radar.adapters.official.now', lambda: datetime(2026, 10, 27, tzinfo=SEOUL))
    calls = []
    unfiltered = [
        [notice(2, '20261001'), notice(3, '20261101')],
        [notice(4, None), notice(5, '20261102')],
        [notice(6, '20261340'), notice(7, '20261103')],
    ]
    def get(url, params):
        calls.append(params.copy())
        if 'cond[rcrt_prgs_yn::EQ]' in params:
            rows, total = [notice(1, '20261001')], 1
        elif 'cond[pbanc_rcpt_bgng_dt::GTE]' in params:
            rows, total = [notice(99, '20261101'), notice(100, '20261001')], 1000
        else:
            rows, total = unfiltered[params['page'] - 1], 1000
        return json.dumps({'data': {'data': rows}, 'matchCount': total}).encode(), 'application/json', url
    source = {'slug': 'kstartup', 'name': 'KStartup', 'config': {
        'scope': 'OPEN', 'page_size': 2, 'max_pages': 4,
        'recent_announcement_pages': 2, 'include_upcoming_announcements': True}}
    a = KStartupApiAdapter(source, SimpleNamespace(get=get))
    acquired = []
    with pytest.raises(SourceFailure, match='API_SCOPE'):
        for candidate in a.discover():
            acquired.append(candidate.source_program_id)
    assert acquired == ['1', '2', '3', '4', '5', '99', '7']
    # Existing OPEN/recent behaviour stays intact; fallback never adds an unknown
    # or invalid date as a future opportunity and never duplicates saved IDs.
    assert len(acquired) == len(set(acquired))
    assert '6' not in acquired and '100' not in acquired
    assert len(calls) == 7  # OPEN + two recent + one failed filter + three fallback.
    assert len(calls[3:]) == source['config']['max_pages']
    assert all('cond[rcrt_prgs_yn::EQ]' not in c for c in calls[3:])
    assert all('cond[pbanc_rcpt_bgng_dt::GTE]' not in c for c in calls[4:])
    coverage = a.pagination.report()
    failed, fallback = coverage['queries'][-2:]
    assert failed['server_filter_verified'] is False
    assert failed['matched_future_records'] == failed['yielded_future_records'] == 1
    assert fallback['actual_scope'] == 'BOUNDED_UNFILTERED_FALLBACK'
    assert fallback['matched_future_records'] == 3 and fallback['yielded_future_records'] == 1
    assert fallback['bounded_window_complete'] and not fallback['pagination_complete']
    assert not coverage['scope_completed']
    assert 'fixture-key' not in str(coverage)


def test_filter_mismatch_with_one_request_budget_still_preserves_verified_future_rows(monkeypatch):
    a, calls = adapter(monkeypatch, [notice(999, '20261101'), notice(5, '20261001')])
    a.config['max_pages'] = 1
    acquired = []
    with pytest.raises(SourceFailure, match='API_SCOPE'):
        for candidate in a.discover():
            acquired.append(candidate.source_program_id)
    assert acquired == ['1', '999']
    assert len(calls) == 2
    assert len(a.pagination.report()['queries']) == 2
    assert not a.pagination.report()['scope_completed']


def test_future_filter_rejects_invalid_calendar_dates_without_guessing(monkeypatch):
    a, _ = adapter(monkeypatch, [notice(999, '20261340'), notice(1000, None)])
    a.config['max_pages'] = 1
    acquired = []
    with pytest.raises(SourceFailure, match='API_SCOPE'):
        for candidate in a.discover():
            acquired.append(candidate.source_program_id)
    assert acquired == ['1']
    assert a.pagination.report()['queries'][-1]['matched_future_records'] == 0


def test_ignored_filter_does_not_turn_a_stalled_fallback_into_success(monkeypatch):
    a, calls = adapter(monkeypatch, [notice(5, '20261001')])
    # The fixture repeats the same unfiltered identity while claiming two rows.
    original = a.http.get
    def get(url, params):
        data, content_type, final = original(url, params)
        payload = json.loads(data)
        if 'cond[pbanc_rcpt_bgng_dt::GTE]' not in params and 'cond[rcrt_prgs_yn::EQ]' not in params:
            payload['matchCount'] = 2
        return json.dumps(payload).encode(), content_type, final
    a.http.get = get
    with pytest.raises(SourceFailure, match='PAGINATION_STALLED'):
        list(a.discover())
    assert not a.pagination.report()['scope_completed']
    assert len(calls) == 4
