"""Regression: the 2026-10-27 issue published one pinned Yonsei notice five times."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import Mock

from radar.adapters.weekly_direct import OfficialChannelAdapter
from radar.identity import deduplicate_publication, normalize_url


URL = 'https://venture.yonsei.ac.kr/community/notice/342'
FACTS = {
    'title': '2026 연세대학교 대학원생 AI 벤처창업경진대회 참가팀 모집',
    'organization': '연세대학교 창업지원단',
    'official_url': URL,
    'application_start_at': None,
    'application_end_at': '2026-11-10T23:59:59+09:00',
}


def row(pid, **changes):
    return {'program_id': pid, 'snapshot': {**FACTS, **changes}}


def test_numeric_yonsei_notice_keeps_identity_across_return_pages():
    assert normalize_url(URL+'?p=2&utm_source=board#top') == URL
    assert normalize_url(URL+'/?p=5&edition=2') == URL+'?edition=2'
    assert normalize_url(URL.replace('/342', '/343')+'?p=2') != URL


def test_p_is_preserved_on_listings_other_hosts_and_non_numeric_routes():
    for url in (
        'https://venture.yonsei.ac.kr/community/notice?p=2',
        'https://other.example/community/notice/342?p=2',
        'https://venture.yonsei.ac.kr/community/notice/current?p=2',
    ):
        assert normalize_url(url) == url


def test_preexisting_pinned_copies_publish_once_even_without_start():
    rows = [row('original')]+[row(f'copy-{p}', official_url=URL+f'?p={p}') for p in range(2, 6)]
    kept, dropped = deduplicate_publication(rows)
    assert [item['program_id'] for item in kept] == ['original']
    assert [item['duplicate_of'] for item in dropped] == ['original']*4
    assert len(rows) == 5  # Publication suppression never mutates stored records.


def test_same_detail_with_distinct_editions_or_declared_dates_is_retained():
    rows = [row('original'),
            row('next-cohort', title=FACTS['title']+' 2기'),
            row('next-period', application_end_at='2026-12-10T23:59:59+09:00'),
            row('different-start', application_start_at='2026-10-01T00:00:00+09:00'),
            row('different-organizer', organization='다른 대학 창업지원단')]
    kept, dropped = deduplicate_publication(rows)
    assert len(kept) == 5 and not dropped


def test_equal_title_and_deadline_do_not_claim_other_incomplete_notices():
    rows = [row('yonsei'),
            row('different-notice', official_url=URL.replace('/342', '/343')),
            row('other-portal', official_url='https://www.bizinfo.go.kr/notice?id=342')]
    kept, dropped = deduplicate_publication(rows)
    assert len(kept) == 3 and not dropped


def test_pinned_copies_are_not_fetched_again_when_following_yonsei_listing():
    registry = json.loads((Path(__file__).parents[1]/'weekly-direct-sources.json').read_text(encoding='utf-8'))
    source = deepcopy(next(s for s in registry if s['slug']=='weekly-yonsei-notices'))
    adapter = OfficialChannelAdapter(source, Mock())
    listing = source['config']['url']
    title = FACTS['title']
    first = f'<a href="{URL}">{title}</a><a class="paging__link next" href="?p=2">2</a>'.encode()
    second = f'<a href="{URL}?p=2">{title}</a><a href="{URL.replace("/342", "/343")}?p=2">{title} 2기</a>'.encode()
    adapter.read_page = Mock(side_effect=[(first, 'text/html', listing),
                                         (second, 'text/html', listing+'?p=2')])
    candidates = list(adapter.discover())
    assert [normalize_url(c.official_detail_url) for c in candidates] == [URL, URL.replace('/342', '/343')]
    assert adapter.pagination.report()['fetched_unique_records'] == 2
    assert adapter.pagination.report()['pages_requested'] == 2

