"""Publication-path regressions for actionability, GFC relevance and dedup.

These need a real database because they assert what is persisted, what is
withheld and what stays auditable. Run with TEST_DATABASE_URL set.
"""
import os
from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest
from core.clock import SEOUL
from radar.models import Program
from radar.weekly import build_briefing, snapshot, announce
from test_database import db  # noqa: F401
from test_weekly import collection

pytestmark = pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), reason='Explicit test database required')
AT = datetime(2026, 9, 15, 15, tzinfo=SEOUL)

RELEVANT = '예비창업자 액셀러레이팅 배치 프로그램 참가팀 모집'
RESTRICTED = '바이오 스타트업 실증(PoC) 지원사업 참여기업 모집'
NOISE = '2026년 소상공인 카드수수료 지원사업 추가모집 공고'


def program(title, *, end=datetime(2027, 1, 1, tzinfo=SEOUL), start=None, kind='FIXED_DATE',
            applicant=None, url='https://example.org/p'):
    return Program(title=title, organization='Agency', official_url=url, support_summary='Official support',
                   applicant_summary=applicant, application_start_at=start, application_end_at=end,
                   application_end_precision='DATE' if end else 'UNKNOWN', deadline_type=kind)


def acquire(db, *programs):
    """Build a weekly collection payload from real stored programs."""
    acquired = collection(db, 0)
    source = db.upsert_source('weekly-k', 'K-Startup', 'KSTARTUP', {})
    rows = []
    for index, item in enumerate(programs):
        saved = db.save_program(item, source['id'], f'pub-{index}', item.official_url, {}, 'Official structured fields')
        rows.append({**saved, 'snapshot': snapshot(item, {}), 'status': 'OPEN'})
    acquired['weekly_programs'] = rows
    return acquired


def items(db, briefing_id):
    with db.transaction() as c:
        return c.execute('select program_id,display_order,change_type,relevance_status,restriction_summary,relevance_version '
                         'from startup_radar.weekly_briefing_items where briefing_id=%s order by display_order',
                         (briefing_id,)).fetchall()


def test_relevant_items_precede_conditional_and_carry_their_restriction(db):
    result = build_briefing(db, acquire(db, program(RESTRICTED, url='https://example.org/bio', applicant='바이오 분야 기업'),
                                        program(RELEVANT, url='https://example.org/acc')), AT)
    rows = items(db, result['briefing_id'])
    assert [row['relevance_status'] for row in rows] == ['GFC_RELEVANT', 'CONDITIONAL']
    assert rows[0]['restriction_summary'] is None
    assert rows[1]['restriction_summary']
    assert all(row['relevance_version'] == 'gfc-v1.1' for row in rows)
    assert result['item_count'] == 2


def test_out_of_scope_and_review_required_are_classified_but_never_published(db):
    conflicted = '소상공인 카드수수료 지원 및 액셀러레이팅 배치 프로그램 모집'
    result = build_briefing(db, acquire(db, program(NOISE, url='https://example.org/noise'),
                                        program(conflicted, url='https://example.org/conflict'),
                                        program(RELEVANT, url='https://example.org/acc')), AT)
    assert result['item_count'] == 1
    assert result['withheld']['OUT_OF_SCOPE'] == 1 and result['withheld']['REVIEW_REQUIRED'] == 1
    with db.transaction() as c:
        # Hidden does not mean discarded: programs, versions and the classification stay.
        assert c.execute('select count(*) n from startup_radar.programs').fetchone()['n'] == 3
        stored = c.execute("select relevance_status,count(*) n from startup_radar.program_relevance "
                           "where relevance_version='gfc-v1.1' group by 1").fetchall()
        assert {row['relevance_status']: row['n'] for row in stored} == \
               {'OUT_OF_SCOPE': 1, 'REVIEW_REQUIRED': 1, 'GFC_RELEVANT': 1}


@pytest.mark.parametrize('case,end,start,kind', [
    ('expired', AT - timedelta(days=1), None, 'FIXED_DATE'),
    ('near', AT + timedelta(hours=47), None, 'FIXED_DATE'),
    ('unknown', None, None, 'UNKNOWN'),
    ('upcoming', AT + timedelta(days=60), AT + timedelta(days=5), 'FIXED_DATE'),
])
def test_unactionable_opportunities_are_withheld_from_the_weekly_article(db, case, end, start, kind):
    result = build_briefing(db, acquire(db, program(RELEVANT, end=end, start=start, kind=kind)), AT)
    assert result['item_count'] == 0
    assert sum(result['withheld'].values()) == 1


@pytest.mark.parametrize('kind', ['ROLLING', 'UNTIL_BUDGET_EXHAUSTED'])
def test_trusted_ongoing_acceptance_still_publishes(db, kind):
    result = build_briefing(db, acquire(db, program(RELEVANT, end=None, kind=kind)), AT)
    assert result['item_count'] == 1


def test_exactly_forty_eight_hours_is_published(db):
    result = build_briefing(db, acquire(db, program(RELEVANT, end=AT + timedelta(hours=48))), AT)
    assert result['item_count'] == 1


def test_cross_portal_duplicate_becomes_one_member_item_with_both_provenances(db):
    kstartup = db.upsert_source('weekly-k', 'K-Startup', 'KSTARTUP', {})
    bizinfo = db.upsert_source('weekly-b', 'BizInfo', 'BIZINFO', {})
    period = dict(start=datetime(2026, 9, 10, tzinfo=SEOUL), end=datetime(2026, 12, 17, tzinfo=SEOUL))
    left = program('베트남 테크페스트(TECHFEST 2026) K-스타트업 통합관 참가기업 모집공고',
                   url='https://www.k-startup.go.kr/notice/1', **period)
    right = program('베트남 테크페스트(TECHFEST 2026) K-스타트업 통합관 참가기업 모집 공고',
                    url='https://www.bizinfo.go.kr/notice/2', **period)
    right.organization = '중소벤처기업부'
    first = db.save_program(left, kstartup['id'], 'ks-1', left.official_url, {}, 'text')
    second = db.save_program(right, bizinfo['id'], 'bz-1', right.official_url, {}, 'text')
    assert first['program_id'] == second['program_id']
    with db.transaction() as c:
        assert c.execute('select count(*) n from startup_radar.program_sources where program_id=%s',
                         (first['program_id'],)).fetchone()['n'] == 2

    # A materially different programme under a similar name stays separate.
    other = program('태국 테크페스트(TECHFEST 2026) K-스타트업 통합관 참가기업 모집공고',
                    url='https://www.bizinfo.go.kr/notice/3', **period)
    assert db.save_program(other, bizinfo['id'], 'bz-2', other.official_url, {}, 'text')['program_id'] != first['program_id']


def test_out_of_scope_program_stays_hidden_until_it_materially_becomes_relevant(db):
    acquired = acquire(db, program(NOISE, url='https://example.org/noise'))
    assert build_briefing(db, acquired, AT)['item_count'] == 0
    # Unchanged next week: still hidden, still not NEW noise in the archive.
    assert build_briefing(db, acquired, AT + timedelta(days=7))['item_count'] == 0
    # The institution rewrites it into a real accelerator call.
    acquired['weekly_programs'][0]['snapshot']['title'] = RELEVANT
    later = build_briefing(db, acquired, AT + timedelta(days=14))
    assert later['item_count'] == 1
    rows = items(db, later['briefing_id'])
    assert rows[0]['change_type'] == 'NEW' and rows[0]['relevance_status'] == 'GFC_RELEVANT'


def test_correction_preserves_publication_identity_and_never_announces(db):
    result = build_briefing(db, acquire(db, program(RELEVANT, url='https://example.org/a'),
                                        program(RELEVANT + ' 2차', url='https://example.org/b')), AT)
    with db.transaction() as c:
        before = c.execute('select id,published_at,revision from startup_radar.weekly_briefings').fetchone()
        keep = c.execute('select program_id from startup_radar.weekly_briefing_items where briefing_id=%s '
                         'order by display_order limit 1', (result['briefing_id'],)).fetchone()
        answer = c.execute("select startup_radar.apply_publication_correction(%s,%s,%s,%s) r",
                           (result['briefing_id'], 'Withdraw an item that should not have been published',
                            '새로 확인 1건 · 변경 0건입니다.',
                            __import__('json').dumps([{'program_id': str(keep['program_id']), 'display_order': 0,
                                                       'relevance_status': 'GFC_RELEVANT', 'restriction_summary': None,
                                                       'relevance_version': 'gfc-v1.1'}]))).fetchone()['r']
        after = c.execute('select id,published_at,revision,item_count from startup_radar.weekly_briefings').fetchone()
        audit = c.execute("select detail from startup_radar.admin_audit where action='WEEKLY_PUBLICATION_CORRECTION'").fetchone()['detail']
    assert answer['retained'] == 1 and answer['withdrawn'] == 1
    assert after['id'] == before['id'] and after['published_at'] == before['published_at']
    assert after['revision'] == before['revision'] + 1 and after['item_count'] == 1
    # The withdrawn snapshots remain recoverable.
    assert len(audit['previous_items']) == 2 and audit['telegram_sent'] is False
    assert announce(db, result['briefing_id'], Mock())['state'] == 'NO_BROADCAST_CHANNEL'


def test_stage_fit_is_persisted_on_items_but_never_part_of_the_material_hash(db):
    from radar.weekly import MATERIAL
    from radar.stage import classify_stage
    assert not any(key.startswith('stage') for key in MATERIAL)
    acquired = acquire(db, program('스타트업 MVP 제작 지원 프로그램 참가팀 모집', url='https://example.org/stage'))
    first = build_briefing(db, acquired, AT)
    with db.transaction() as c:
        row = c.execute('select stage_codes,stage_version,material_hash from startup_radar.weekly_briefing_items where briefing_id=%s',
                        (first['briefing_id'],)).fetchone()
        stored = c.execute("select stage_codes,method from startup_radar.program_stage_fit where stage_version='gfc-stage-v1.0'").fetchone()
    assert row['stage_codes'] == ['STAGE_3'] and row['stage_version'] == 'gfc-stage-v1.0'
    assert stored['stage_codes'] == ['STAGE_3'] and stored['method'] == 'DETERMINISTIC_RULES_V1'
    # Same material facts next week with a different stage decision: nothing is an UPDATE.
    acquired['weekly_programs'][0]['snapshot'] = dict(acquired['weekly_programs'][0]['snapshot'])
    with db.transaction() as c:
        c.execute("update startup_radar.program_stage_fit set stage_codes='{STAGE_1}' where stage_version='gfc-stage-v1.0'")
    second = build_briefing(db, acquired, AT + timedelta(days=7))
    assert second['item_count'] == 0 and second['updated_count'] == 0
    with db.transaction() as c:
        assert c.execute("select count(*) n from startup_radar.program_change_events").fetchone()['n'] <= 1  # only the original NEW
        assert c.execute('select material_hash from startup_radar.weekly_briefing_items where briefing_id=%s',
                         (first['briefing_id'],)).fetchone()['material_hash'] == row['material_hash']


def test_stage_and_relevance_are_recorded_independently(db):
    result = build_briefing(db, acquire(db,
        program(RESTRICTED + ' PoC 실증', url='https://example.org/bio', applicant='바이오 분야 법인사업자만'),
        program('오픈이노베이션 투자 유치 액셀러레이팅 참가팀 모집', url='https://example.org/oi')), AT)
    rows = items(db, result['briefing_id'])
    assert [r['relevance_status'] for r in rows] == ['GFC_RELEVANT', 'CONDITIONAL']
    with db.transaction() as c:
        stages = {r['relevance_status']: r['stage_codes'] for r in c.execute(
            'select relevance_status,stage_codes from startup_radar.weekly_briefing_items where briefing_id=%s', (result['briefing_id'],)).fetchall()}
    assert 'STAGE_4' in stages['GFC_RELEVANT']
    # "법인사업자만" in eligibility did not push the bio programme to STAGE_4.
    assert stages['CONDITIONAL'] == ['STAGE_3']
