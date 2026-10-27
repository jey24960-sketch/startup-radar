from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace

from core.clock import SEOUL
from radar.adapters.base import Candidate, SourceFailure
from radar.models import Program
from radar.official_facts import (
    _body, apply_evidence, enrich_official, evidence_signature, should_enrich,
)

AT = datetime(2026, 10, 27, 9, tzinfo=SEOUL)


def program(**updates):
    return Program(title='예비창업자 사업화 지원사업 모집', organization='테스트기관',
                   official_url='https://www.bizinfo.go.kr/sii/notice',
                   support_summary='사업화 자금 지원',
                   application_start_at=AT-timedelta(days=1),
                   application_end_at=AT+timedelta(days=20),
                   application_start_precision='DATE', application_end_precision='DATE',
                   deadline_type='FIXED_DATE').model_copy(update=updates)


class Database:
    def __init__(self, raw=None):
        self.raw = raw

    @contextmanager
    def transaction(self):
        yield self

    def execute(self, *_):
        return SimpleNamespace(fetchone=lambda: {'raw_metadata': self.raw} if self.raw else None)


def test_reuses_official_body_without_model_or_http_request():
    p = program()
    cached = {'signature': evidence_signature(p, {}), 'status': 'SUCCESS',
              'text': '공식 내용: 액셀러레이팅과 멘토링',
              'expires_at': (AT+timedelta(days=1)).isoformat()}
    db = Database({'_official_detail': cached})
    candidate = Candidate('bizinfo', 'id', p.official_url, p.official_url, p.title, {})
    result, text, meta = enrich_official(db, {'id': 'source'}, object(), candidate, p, AT)
    assert meta == {'status': 'SUCCESS', 'cache_hit': True, 'failure': None}
    assert text in result.support_summary
    assert candidate.raw_metadata['_official_detail'] == cached


def test_material_change_and_expiry_force_public_html_refresh():
    p = program()
    called = []
    http = SimpleNamespace(get=lambda url: (
        called.append(url) or b'<div class="support_project_detail">New support facts</div>',
        'text/html', url))
    adapter = SimpleNamespace(source={'adapter': 'BIZINFO'}, http=http)
    old = {'signature': evidence_signature(p, {}), 'status': 'SUCCESS', 'text': 'old',
           'expires_at': (AT-timedelta(seconds=1)).isoformat()}
    candidate = Candidate('bizinfo', 'id', p.official_url, p.official_url, p.title, {})
    result, text, meta = enrich_official(Database({'_official_detail': old}),
                                       {'id': 'source'}, adapter, candidate, p, AT)
    assert len(called) == 1 and not meta['cache_hit']
    assert 'New support facts' in result.support_summary
    assert evidence_signature(p, {'inqireCo': '1'}) == evidence_signature(p, {'inqireCo': '99'})
    assert evidence_signature(p, {}) != evidence_signature(p.model_copy(update={'title': '변경'}), {})


def test_missing_body_preserves_api_facts_and_visible_failure():
    p = program()
    http = SimpleNamespace(get=lambda url: (b'<html>menu only</html>', 'text/html', url))
    adapter = SimpleNamespace(source={'adapter': 'BIZINFO'}, http=http)
    candidate = Candidate('bizinfo', 'id', p.official_url, p.official_url, p.title, {})
    result, text, meta = enrich_official(Database(), {'id': 'source'}, adapter, candidate, p, AT)
    assert result == p and text is None
    assert meta['failure']['kind'] == 'DETAIL_PARSE'
    assert meta['failure']['stage'] == 'DETAIL_ENRICHMENT'


def test_bizinfo_nested_document_parser_ignores_related_opportunities():
    page = ('<html><body>navigation</body></html><html><body>'
            '<div class="support_project_detail">실제 사업화 지원 내용</div>'
            '<div class="similar_announcement">채용 모집 다른 공고</div></body></html>').encode()
    adapter = SimpleNamespace(source={'adapter': 'BIZINFO'},
                              http=SimpleNamespace(get=lambda url: (page, 'text/html', url)))
    text, _ = _body(adapter, SimpleNamespace(official_detail_url='https://www.bizinfo.go.kr/a'))
    assert '사업화' in text and '채용' not in text and 'navigation' not in text


def test_datetime_refinement_requires_matching_official_calendar_day():
    p = program()
    result = apply_evidence(p, {'status': 'SUCCESS', 'text':
        '신청기간\n2026.10.26(월) 10:00 ~ 2026.11.16(월) 13:00\n행사 2026.11.20 09:00'})
    assert result.application_start_at.hour == 10
    assert result.application_end_at.hour == 13
    assert result.application_end_precision == 'DATETIME'
    unchanged = apply_evidence(p, {'status': 'SUCCESS', 'text': '행사일 2026.11.16 12:00'})
    assert unchanged.application_end_at == p.application_end_at
    for separator in ('\n', ' '):
        same_day_event = apply_evidence(p, {'status': 'SUCCESS', 'text':
            '신청기간\n2026.10.26 ~ 2026.11.16' + separator + '행사일 2026.11.16 09:00'})
        assert same_day_event.application_end_at == p.application_end_at
        assert same_day_event.application_end_precision == 'DATE'


def test_closed_and_unrelated_programs_do_not_generate_detail_traffic():
    assert not should_enrich(program(application_end_at=AT-timedelta(days=1)), AT)
    assert not should_enrich(program(title='경력 직원 채용', support_summary='사원 채용'), AT)
    assert should_enrich(program(), AT)


def test_failed_host_does_not_repeat_network_failures_for_every_api_record():
    calls = []
    def fail(url):
        calls.append(url)
        raise SourceFailure('ROBOTS_UNAVAILABLE', 'Policy verification timed out', True)
    adapter = SimpleNamespace(source={'adapter': 'BIZINFO'}, http=SimpleNamespace(get=fail))
    p = program()
    first = Candidate('bizinfo', 'one', p.official_url, p.official_url, p.title, {})
    second = Candidate('bizinfo', 'two', p.official_url, p.official_url, p.title, {})
    assert enrich_official(Database(), {'id': 'source'}, adapter, first, p, AT)[2]['status'] == 'FAILED'
    result, _, diagnostic = enrich_official(Database(), {'id': 'source'}, adapter, second, p, AT)
    assert diagnostic['status'] == 'DEFERRED' and result == p and len(calls) == 1


def test_optional_evidence_budget_never_requests_more_bodies_or_discards_api_facts(monkeypatch):
    monkeypatch.setattr('radar.official_facts.MAX_NEW_REQUESTS', 1)
    calls = []
    def fetch(url):
        calls.append(url)
        return b'<div class="support_project_detail">Official facts</div>', 'text/html', url
    adapter = SimpleNamespace(source={'adapter': 'BIZINFO'}, http=SimpleNamespace(get=fetch))
    p = program()
    for i in range(3):
        c = Candidate('bizinfo', str(i), p.official_url, p.official_url, p.title, {})
        result, _, diagnostic = enrich_official(Database(), {'id': 'source'}, adapter, c, p, AT)
        assert result.title == p.title and result.application_end_at == p.application_end_at
        assert diagnostic['status'] == ('SUCCESS' if i == 0 else 'DEFERRED')
    assert len(calls) == 1


def test_conflicting_publisher_deadline_is_withheld_without_deleting_api_evidence():
    from radar.actionability import actionability
    p = program()
    item = {'status': 'SUCCESS', 'text': '신청기간: 2026.10.26 ~ 2026.11.10'}
    result = apply_evidence(p, item)
    assert result.application_end_at is None and item['application_period_conflict']
    assert actionability(result.model_dump(mode='json'), AT) == (False, 'DEADLINE_UNKNOWN')
    assert p.application_end_at is not None
    assert '2026.11.10' in result.support_summary
    precise = p.model_copy(update={'application_end_precision': 'DATETIME'})
    conflicting_time = apply_evidence(precise, {'status': 'SUCCESS', 'text':
        '신청기간: 2026.10.26 10:00 ~ 2026.11.16 13:00'})
    assert conflicting_time.application_end_at is None


def test_publisher_closed_statement_blocks_a_formally_future_api_deadline():
    from radar.weekly import snapshot
    from radar.actionability import actionability
    p = program()
    page = '<div class="support_project_detail">현재 모집이 마감되었습니다.</div>'.encode()
    adapter = SimpleNamespace(source={'adapter': 'BIZINFO'},
        http=SimpleNamespace(get=lambda url: (page, 'text/html', url)))
    candidate = Candidate('bizinfo', 'id', p.official_url, p.official_url, p.title, {})
    result, _, _ = enrich_official(Database(), {'id': 'source'}, adapter, candidate, p, AT)
    assert result.application_end_at == p.application_end_at
    assert actionability(snapshot(result, candidate.raw_metadata), AT) == (False, 'CLOSED_SOURCE_STATUS')
