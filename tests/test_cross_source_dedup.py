"""One notice republished by the second national portal is one opportunity.

The regression fixture is the real 2026-09-15 case: the same Vietnam TECHFEST
recruitment was carried by both K-Startup and BizInfo with different publisher
IDs, different canonical hosts, different responsible organizations and a
one-character title difference, and reached members twice.
"""
from datetime import datetime

from core.clock import SEOUL
from radar.identity import CROSS_SOURCE_TITLE_MIN, cross_source_key, deduplicate_publication

TECHFEST_START = '2026-09-10T00:00:00+09:00'
TECHFEST_END = '2026-09-17T23:59:59.999999+09:00'
KSTARTUP_TECHFEST = {
    'title': '베트남 테크페스트(TECHFEST 2026) K-스타트업 통합관 참가기업 모집공고',
    'organization': '창업진흥원장', 'official_url': 'https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do',
    'application_start_at': TECHFEST_START, 'application_end_at': TECHFEST_END}
BIZINFO_TECHFEST = {
    'title': '베트남 테크페스트(TECHFEST 2026) K-스타트업 통합관 참가기업 모집 공고',
    'organization': '중소벤처기업부', 'official_url': 'https://www.bizinfo.go.kr/web/lay1/bbs/S1T122C128/AS/74/view.do',
    'application_start_at': TECHFEST_START, 'application_end_at': TECHFEST_END}


def item(facts, program_id):
    return {'program_id': program_id, 'version_id': f'v-{program_id}', 'snapshot': facts}


def test_same_notice_from_both_portals_shares_one_identity():
    # Title differs only by a space; organization and host differ entirely.
    assert KSTARTUP_TECHFEST['title'] != BIZINFO_TECHFEST['title']
    assert KSTARTUP_TECHFEST['organization'] != BIZINFO_TECHFEST['organization']
    left = cross_source_key(KSTARTUP_TECHFEST['title'], TECHFEST_START, TECHFEST_END)
    right = cross_source_key(BIZINFO_TECHFEST['title'], TECHFEST_START, TECHFEST_END)
    assert left is not None and left == right


def test_publication_collapses_the_duplicate_to_one_member_item():
    kept, dropped = deduplicate_publication([item(BIZINFO_TECHFEST, 'biz'), item(KSTARTUP_TECHFEST, 'ks')])
    assert [row['program_id'] for row in kept] == ['biz']
    assert [row['duplicate_of'] for row in dropped] == ['biz']


def test_similar_but_materially_different_programs_stay_separate():
    other_period = {**KSTARTUP_TECHFEST, 'application_end_at': '2026-10-17T23:59:59.999999+09:00'}
    other_name = {**KSTARTUP_TECHFEST, 'title': '태국 테크페스트(TECHFEST 2026) K-스타트업 통합관 참가기업 모집공고'}
    kept, dropped = deduplicate_publication([item(BIZINFO_TECHFEST, 'a'), item(other_period, 'b'), item(other_name, 'c')])
    assert len(kept) == 3 and not dropped


def test_generic_facts_never_establish_a_cross_source_claim():
    # Too short to be specific, or missing half the period: no claim at all.
    assert cross_source_key('모집 공고', TECHFEST_START, TECHFEST_END) is None
    assert cross_source_key(KSTARTUP_TECHFEST['title'], None, TECHFEST_END) is None
    assert cross_source_key(KSTARTUP_TECHFEST['title'], TECHFEST_START, None) is None
    assert cross_source_key(None, TECHFEST_START, TECHFEST_END) is None
    assert len('모집공고') < CROSS_SOURCE_TITLE_MIN


def test_short_titled_rows_are_all_retained():
    generic = {'title': '창업 모집', 'application_start_at': TECHFEST_START, 'application_end_at': TECHFEST_END}
    kept, dropped = deduplicate_publication([item(generic, 'a'), item(dict(generic), 'b')])
    assert len(kept) == 2 and not dropped


def test_datetime_and_iso_string_periods_agree():
    # save_program passes datetimes; the publication path passes stored ISO text.
    start = datetime(2026, 9, 10, tzinfo=SEOUL)
    end = datetime(2026, 9, 17, 23, 59, 59, 999999, tzinfo=SEOUL)
    assert cross_source_key(KSTARTUP_TECHFEST['title'], start, end) == \
           cross_source_key(KSTARTUP_TECHFEST['title'], TECHFEST_START, TECHFEST_END)
    # An equal wall clock in another zone is a different instant, not a match.
    assert cross_source_key(KSTARTUP_TECHFEST['title'], start, end) != \
           cross_source_key(KSTARTUP_TECHFEST['title'], TECHFEST_START.replace('+09:00', '+00:00'), TECHFEST_END)
    # A naive timestamp is never comparable and must not produce a key.
    assert cross_source_key(KSTARTUP_TECHFEST['title'], start.replace(tzinfo=None), end) is None
