from datetime import datetime, timedelta
from uuid import uuid4

from core.clock import SEOUL
from radar.models import Program
from radar.opportunity_facts import publication_review_note
from radar.weekly import stored_candidates
from radar.early_announcements import candidate_decision

AT = datetime(2026, 10, 27, 9, tzinfo=SEOUL)


def stored(*, end=AT+timedelta(days=10), reasons=(), participation='UNKNOWN'):
    version = uuid4()
    p = Program(title='예비창업자 사업화 지원 프로그램 모집', organization='공식기관',
        official_url='https://example.org/official', support_summary='예비창업자 사업화 지원',
        application_start_at=AT-timedelta(days=2), application_end_at=end,
        application_start_precision='DATE', application_end_precision='DATE' if end else 'UNKNOWN',
        deadline_type='FIXED_DATE' if end else 'UNKNOWN')
    facts = {'recruitment_confirmed': True, 'participation': participation,
             'review_reasons': list(reasons)}
    return {'program_id': uuid4(), 'version_id': version, 'observation_version_id': version,
        'normalized': p.model_dump(mode='json'), 'source_config': {'weekly_direct': True},
        'source_adapter': 'HTML', 'raw_metadata': {'weekly_decision': 'REVIEW',
            'weekly_reason': 'PARTICIPATION_UNKNOWN', 'weekly_direct_facts': facts},
        'extraction_metadata': {'provider': 'official_html_weekly'}}


def test_confirmed_recruitment_with_unclear_participation_enters_labelled_appendix():
    rows = stored_candidates([stored()], AT)
    assert len(rows) == 1
    assert '참여 형태' in rows[0]['snapshot']['review_note']
    assert rows[0]['snapshot']['application_end_at'] is not None
    ok, reason = candidate_decision(rows[0]['snapshot'], AT)
    assert not ok and reason == 'SOURCE_CONFIRMATION_REQUIRED'


def test_uncertain_dates_and_source_period_conflicts_stay_out_of_publication():
    assert stored_candidates([stored(end=None)], AT) == []
    assert stored_candidates([stored(reasons=('APPLICATION_PERIOD_CONFLICT',))], AT) == []
    assert publication_review_note('REVIEW', 'CURRENT_PERIOD_UNKNOWN') is None
    assert publication_review_note('REVIEW', 'RECRUITMENT_UNCONFIRMED') is None


def test_multiple_application_links_have_an_explicit_member_facing_note():
    assert '신청 경로' in publication_review_note('REVIEW', 'MULTIPLE_APPLICATION_LINKS')
    assert publication_review_note('ACCEPTED', 'MULTIPLE_APPLICATION_LINKS') is None
