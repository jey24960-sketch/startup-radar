"""The reviewed Lotte news channel survives its 2026 official site redesign."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from unittest.mock import Mock

from bs4 import BeautifulSoup
import pytest

from core.clock import SEOUL
from radar.adapters.base import Candidate, SourceFailure
from radar.adapters.weekly_direct import OfficialChannelAdapter
from radar.opportunity_facts import labeled_period, weekly_decision

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests' / 'fixtures'
SOURCE = next(s for s in json.loads((ROOT / 'weekly-direct-sources.json').read_text(encoding='utf-8'))
              if s['slug'] == 'weekly-lotte-recruitment')
URL = ('https://lotteventures.com/news/'
       '2026-l-camp-14gi-l-camp-miraesigdan-6gi-camyeogieob-mojib')
TITLE = '2026 L-CAMP 14기 & L-CAMP : 미래식단 6기 참여기업 모집!'
AT = datetime(2026, 10, 27, 16, tzinfo=SEOUL)


def adapter_with(html, url=URL):
    adapter = OfficialChannelAdapter(deepcopy(SOURCE), Mock())
    adapter.read_page = Mock(return_value=(html, 'text/html', url))
    return adapter


def candidate(url=URL):
    return Candidate(SOURCE['slug'], url, SOURCE['config']['url'], url, TITLE)


def test_registry_targets_new_official_recruitment_news_and_stable_slug_identity():
    cfg = SOURCE['config']
    assert cfg['url'] == 'https://lotteventures.com/news'
    assert set(cfg['allowed_hosts']) == {'lotteventures.com', 'www.lotteventures.com'}
    assert cfg['submission_path_prefix'] == '/news/'
    assert cfg['identity_query_keys'] == []
    assert cfg['require_detail_title'] is True
    assert cfg['max_pages'] == 1 and cfg['single_page_scope'] is True


def test_actual_news_cards_find_seven_recruitments_and_skip_general_events():
    html = (FIXTURES / 'lotte_2026_news_list.html').read_bytes()
    assert not BeautifulSoup(html, 'lxml').select('a[href*="/news/news?"][href*="code="]')
    adapter = adapter_with(html, SOURCE['config']['url'])
    found = list(adapter.discover())
    assert len(found) == 7
    assert found[0].title == TITLE
    assert found[0].official_detail_url == URL
    assert all('모집' in row.title for row in found)
    coverage = adapter.pagination.report()
    assert coverage['pagination_complete'] and coverage['non_recruitment_excluded'] == 2
    assert coverage['pages_requested'] == 1
    assert coverage['scope'] == 'CONFIGURED_CHANNEL'


def test_administrative_notice_and_news_navigation_are_not_recruitments():
    html = b'''<nav><a href="/news">News</a></nav><main>
        <a href="/news/privacy"><h2>Privacy policy update</h2></a>
        <a href="/news/accounts"><h2>Annual financial statements</h2></a></main>'''
    adapter = adapter_with(html, SOURCE['config']['url'])
    assert list(adapter.discover()) == []
    assert adapter.pagination.report()['non_recruitment_excluded'] == 2


def test_full_article_includes_closed_banner_outside_prose_without_inventing_form():
    html = (FIXTURES / 'lotte_2026_lcamp_closed.html').read_bytes()
    assert '마감됐습니다' not in BeautifulSoup(html, 'lxml').select_one('.prose').get_text()
    adapter = adapter_with(html)
    row = candidate()
    detail = adapter.fetch_detail(row)
    program = adapter.normalize(row, detail, [])
    facts = row.raw_metadata['weekly_direct_facts']
    assert detail.title == TITLE and '마감됐습니다' in detail.text
    assert program.application_start_at == datetime(2026, 2, 23, tzinfo=SEOUL)
    assert program.application_end_at == datetime(2026, 3, 31, 16, tzinfo=SEOUL)
    assert program.application_url is None
    assert facts['recruitment_closed'] is True
    assert facts['evidence']['closure']['url'] == URL
    assert weekly_decision(program, facts, AT) == ('EXCLUDED', 'CLOSED_SOURCE_STATUS')


def test_tracking_query_is_ignored_but_different_official_slugs_remain_distinct():
    html = (FIXTURES / 'lotte_2026_lcamp_closed.html').read_bytes()
    ids = []
    for url in (URL, URL + '?utm_source=newsletter', URL + '-different-cohort'):
        adapter = adapter_with(html, url)
        row = candidate(url)
        program = adapter.normalize(row, adapter.fetch_detail(row), [])
        ids.append(row.source_program_id)
        assert '?' not in program.official_url
    assert ids[0] == ids[1] and ids[0] != ids[2]


def test_missing_current_official_article_heading_fails_closed():
    adapter = adapter_with(b'<main><h1>News</h1><p>Site structure changed again.</p></main>')
    with pytest.raises(SourceFailure, match='Required official program heading missing'):
        adapter.fetch_detail(candidate())


def test_undated_program_does_not_infer_dates_from_news_publication_or_clock():
    html = ('<main><article><time>2026년 10월 27일</time><h1>' + TITLE + '</h1>'
            '<div class="prose"><p>다음 모집 소식을 안내합니다. '
            '공식 모집 기간과 신청 방법은 추후 공지합니다.</p></div></article></main>').encode('utf-8')
    adapter = adapter_with(html)
    row = candidate()
    program = adapter.normalize(row, adapter.fetch_detail(row), [])
    assert program.application_start_at is None and program.application_end_at is None
    assert weekly_decision(program, row.raw_metadata['weekly_direct_facts'], AT)[0] != 'ACCEPTED'


@pytest.mark.parametrize('label', ['모집 기간', '신청 기간', '접수 기간', '모집 일정'])
def test_explicit_period_label_wins_over_earlier_closed_banner(label):
    text = ('이 모집은 2026년 3월 31일에 마감됐습니다.\n'
            f"{label} : '26.02.23(월) ~ 03.31(화) 16:00 까지")
    start, end, _, _, evidence = labeled_period(text, 2026)
    assert start == datetime(2026, 2, 23, tzinfo=SEOUL)
    assert end == datetime(2026, 3, 31, 16, tzinfo=SEOUL)
    assert evidence.startswith(label)


def test_existing_bare_recruitment_range_still_works_without_period_label():
    start, end, _, _, _ = labeled_period('모집은 2026.2.23 ~ 3.31 16:00까지', 2026)
    assert start == datetime(2026, 2, 23, tzinfo=SEOUL)
    assert end == datetime(2026, 3, 31, 16, tzinfo=SEOUL)
