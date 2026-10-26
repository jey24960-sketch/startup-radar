"""Daily discoveries remain available to the one weekly member publication."""
import os
from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from core.clock import SEOUL
from radar.models import Program
from radar.opportunity_facts import weekly_decision
from radar.weekly import (
    build_briefing, load_stored_candidates, merge_candidates, snapshot, stored_candidates,
)
from test_database import db  # noqa: F401
from test_weekly import collection

AT = datetime(2026, 10, 13, 9, tzinfo=SEOUL)
RELEVANT = '예비창업자 액셀러레이팅 배치 프로그램 참가팀 모집'
DB = pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'), reason='Explicit test database required')


def fixture_program():
    return Program(title=RELEVANT, organization='Agency', official_url='https://example.org/upcoming',
        support_summary='초기 창업팀 MVP 제작 및 액셀러레이팅 지원',
        application_start_at=AT+timedelta(days=4), application_start_precision='DATE',
        application_end_at=AT+timedelta(days=18), application_end_precision='DATE', deadline_type='FIXED_DATE')


def stored_row(*, direct=False, decision='ACCEPTED', version_match=True, raw=None):
    version_id = uuid4()
    return {
        'program_id': uuid4(), 'version_id': version_id,
        'observation_version_id': version_id if version_match else uuid4(),
        'normalized': fixture_program().model_dump(mode='json'),
        'source_config': {'weekly_direct': True, 'policy_status': 'APPROVED'} if direct else {},
        'extraction_metadata': {'provider': 'official_html_weekly' if direct else 'structured_api_weekly'},
        'raw_metadata': raw if raw is not None else {
            'weekly_decision': decision,
            'weekly_direct_facts': {'recruitment_confirmed': True, 'participation': 'TEAM_RECRUITMENT'},
        },
    }


def test_upcoming_direct_notice_is_accepted_before_application_start():
    assert weekly_decision(fixture_program(),
        {'recruitment_confirmed': True, 'participation': 'TEAM_RECRUITMENT'}, AT) == \
        ('ACCEPTED', 'EXPLICIT_UPCOMING_RECRUITMENT')


def test_upcoming_direct_requires_complete_dates_and_confirmed_recruitment():
    program = fixture_program()
    program.application_end_at = None
    assert weekly_decision(program,
        {'recruitment_confirmed': True, 'participation': 'TEAM_RECRUITMENT'}, AT) == \
        ('REVIEW', 'UPCOMING_PERIOD_UNKNOWN')
    assert weekly_decision(fixture_program(),
        {'recruitment_confirmed': False, 'participation': 'TEAM_RECRUITMENT'}, AT)[0] == 'REVIEW'


def test_latest_version_provenance_preserves_attachments_without_older_version_fallback():
    row = stored_row(raw={'flpthNm': 'https://example.org/official.pdf'})
    candidate = stored_candidates([row], AT)[0]
    assert candidate['version_id'] == row['version_id']
    assert candidate['snapshot']['attachments'] == ['https://example.org/official.pdf']
    assert candidate['snapshot']['application_start_at'] == fixture_program().application_start_at.isoformat()
    assert stored_candidates([stored_row(version_match=False)], AT) == []


@pytest.mark.parametrize('decision', ['REVIEW', 'EXCLUDED'])
def test_direct_review_and_exclusion_never_resurrect_older_accepted_provenance(decision):
    api = stored_row()
    direct = stored_row(direct=True, decision=decision)
    direct['program_id'] = api['program_id']
    assert stored_candidates([api, direct], AT) == []
    assert stored_candidates([direct, api], AT) == []


def test_identity_conflicts_and_cancelled_direct_recruitment_stay_blocked():
    assert stored_candidates([stored_row(raw={'weekly_duplicate_conflict': True})], AT) == []
    cancelled = stored_row(direct=True)
    cancelled['raw_metadata']['weekly_direct_facts']['cancelled'] = True
    assert stored_candidates([cancelled], AT) == []


def test_older_ai_or_unattributed_observations_are_not_promoted_to_publication():
    for provider in (None, 'anthropic', 'injected'):
        row = stored_row()
        row['extraction_metadata'] = {'provider': provider}
        assert stored_candidates([row], AT) == []


def test_new_collection_wins_without_discarding_earlier_daily_discovery():
    first, second = stored_row(), stored_row()
    old = stored_candidates([first, second], AT)
    fresh = {**old[0], 'snapshot': {**old[0]['snapshot'], 'title': 'Verified corrected title'}}
    merged = merge_candidates(old, [fresh])
    assert len(merged) == 2
    assert next(row for row in merged if row['program_id'] == fresh['program_id'])['snapshot']['title'] == 'Verified corrected title'


@DB
def test_daily_saved_upcoming_notice_reaches_weekly_issue_when_absent_from_current_api_page(db):
    # No runtime clock is fabricated: freshness uses the real database observation.
    reference = datetime.now(SEOUL)
    acquired = collection(db, 0)
    source = db.upsert_source('daily-stored-official', 'Daily API', 'KSTARTUP', {})
    program = fixture_program()
    program.application_start_at = reference+timedelta(days=3)
    program.application_end_at = reference+timedelta(days=20)
    saved = db.save_program(program, source['id'], 'stored-1', program.official_url,
                            {'flpthNm': 'https://example.org/daily.pdf'}, 'Official structured facts',
                            extraction_metadata={'provider': 'structured_api_weekly'})
    result = build_briefing(db, acquired, reference)
    assert result['published'] and result['item_count'] == 1
    with db.transaction() as c:
        item = c.execute('select * from startup_radar.weekly_briefing_items where briefing_id=%s',
                         (result['briefing_id'],)).fetchone()
        assert item['program_id'] == saved['program_id']
        assert item['snapshot']['attachments'] == ['https://example.org/daily.pdf']
    # A second collection never changes the published issue or duplicates it.
    assert build_briefing(db, acquired, reference)['unchanged']


@DB
def test_stale_disabled_and_deferred_sources_are_not_revived_from_storage(db):
    reference = datetime.now(SEOUL)
    good = db.upsert_source('recent-api', 'API', 'BIZINFO', {})
    stale = db.upsert_source('stale-api', 'Old API', 'KSTARTUP', {})
    disabled = db.upsert_source('disabled-api', 'Disabled API', 'KSTARTUP', {})
    deferred = db.upsert_source('deferred-html', 'Deferred HTML', 'HTML',
                               {'weekly_direct': True, 'policy_status': 'DEFERRED'})
    pids = {}
    for source in (good, stale, disabled, deferred):
        program = fixture_program()
        program.title += ' '+source['slug']
        program.official_url = 'https://example.org/'+source['slug']
        program.application_start_at = reference+timedelta(days=3)
        program.application_end_at = reference+timedelta(days=20)
        pids[source['slug']] = db.save_program(program, source['id'], source['slug'], program.official_url,
            {'weekly_decision': 'ACCEPTED', 'weekly_direct_facts': {'recruitment_confirmed': True,
             'participation': 'TEAM_RECRUITMENT'}}, 'Official facts',
             extraction_metadata={'provider': 'official_html_weekly' if source['adapter'] == 'HTML'
                                  else 'structured_api_weekly'})['program_id']
    with db.transaction() as c:
        c.execute("update startup_radar.program_sources set last_seen_at=now()-interval '15 days' where source_id=%s", (stale['id'],))
        c.execute('update startup_radar.sources set enabled=false where id=%s', (disabled['id'],))
    loaded = load_stored_candidates(db, reference)
    assert {row['program_id'] for row in loaded} == {pids['recent-api']}


@DB
def test_collection_runtime_does_not_reduce_the_required_seven_days(db):
    reference = datetime.now(SEOUL)-timedelta(minutes=20)
    acquired = collection(db, 0)
    source = db.upsert_source('slow-collection', 'API', 'KSTARTUP', {})
    program = fixture_program()
    program.application_start_at = reference-timedelta(days=1)
    # This passed the old worker-start comparison but is under seven days at
    # actual publication, after a 20-minute collection.
    program.application_end_at = reference+timedelta(days=7)
    saved = db.save_program(program, source['id'], 'slow-1', program.official_url, {}, 'Official facts')
    acquired['weekly_programs'] = [{**saved, 'snapshot': snapshot(program, {})}]
    result = build_briefing(db, acquired, reference, database_clock=True)
    assert result['item_count'] == 0
    assert result['withheld']['NEAR_DEADLINE'] == 1


@DB
def test_production_gate_and_recorded_publication_share_the_database_clock(db):
    reference = datetime.now(SEOUL)
    acquired = collection(db, 0)
    source = db.upsert_source('publication-clock', 'API', 'KSTARTUP', {})
    program = fixture_program()
    program.application_start_at = reference-timedelta(days=1)
    program.application_end_at = reference+timedelta(days=7, minutes=5)
    saved = db.save_program(program, source['id'], 'clock-1', program.official_url, {}, 'Official facts')
    acquired['weekly_programs'] = [{**saved, 'snapshot': snapshot(program, {})}]
    result = build_briefing(db, acquired, reference-timedelta(minutes=20), database_clock=True)
    assert result['item_count'] == 1
    with db.transaction() as c:
        published_at = c.execute('select published_at from startup_radar.weekly_briefings where id=%s',
                                 (result['briefing_id'],)).fetchone()['published_at']
    assert program.application_end_at-published_at >= timedelta(days=7)
