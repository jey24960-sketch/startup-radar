"""Closed official API titles cannot bypass weekly or early-notice gates."""
from datetime import datetime,timedelta

import pytest
from core.clock import SEOUL
from radar.actionability import actionability
from radar.early_announcements import candidate_decision

AT=datetime(2026,10,28,12,tzinfo=SEOUL)


def api_facts(title='예비창업자 MVP 제작 및 액셀러레이팅 프로그램 모집',**updates):
    return {
        'title':title,'organization':'공식 창업 지원기관',
        'applicant_summary':'예비창업자와 초기 창업팀을 대상으로 합니다.',
        'support_summary':'예비창업팀의 MVP 제품 개발, 시제품 제작과 고객 검증을 지원하는 액셀러레이팅 프로그램입니다.',
        'application_start_at':(AT+timedelta(days=1)).isoformat(),
        'application_end_at':(AT+timedelta(days=8)).isoformat(),
        'application_start_precision':'DATETIME','application_end_precision':'DATETIME',
        'deadline_type':'FIXED_DATE','official_url':'https://example.org/official-notice',
        'rcrt_prgs_yn':'Y',**updates,
    }


@pytest.mark.parametrize('badge',['[마감]','[접수종료]','[모집 마감]','【신청 종료】'])
@pytest.mark.parametrize('source',['kstartup','bizinfo'])
def test_future_deadline_and_api_open_flag_do_not_override_explicit_title_closure(badge,source):
    facts=api_facts(title=badge+' 예비창업자 MVP 제작 및 액셀러레이팅 프로그램 모집',source=source)
    assert actionability(facts,AT)==(False,'CLOSED_SOURCE_STATUS')
    assert candidate_decision(facts,AT)==(False,'CLOSED_SOURCE_STATUS')


@pytest.mark.parametrize('decide',[actionability,candidate_decision])
def test_explicit_structured_closed_fact_is_also_honored(decide):
    assert decide(api_facts(recruitment_closed=True),AT)==(False,'CLOSED_SOURCE_STATUS')


@pytest.mark.parametrize('title',[
    '마감임박 예비창업자 MVP 제작 및 액셀러레이팅 프로그램 모집',
    '[마감 예정] 예비창업자 MVP 제작 및 액셀러레이팅 프로그램 모집',
])
def test_imminent_or_scheduled_deadline_words_keep_the_existing_qualification(title):
    facts=api_facts(title=title)
    assert actionability(facts,AT)==(True,'PREANNOUNCEMENT')
    assert candidate_decision(facts,AT)==(True,'SEVEN_DAY_WINDOW_LOST_IF_WAITING')


def test_bracketed_imminent_label_is_not_a_closed_badge():
    facts=api_facts(title='[마감임박] 예비창업자 MVP 제작 및 액셀러레이팅 프로그램 모집')
    assert actionability(facts,AT)==(True,'PREANNOUNCEMENT')
    # Preserve the separate existing relevance classifier's outcome; this
    # change must not turn that label into a CLOSED_SOURCE_STATUS decision.
    assert candidate_decision(facts,AT)[1]!='CLOSED_SOURCE_STATUS'


def test_api_summary_closure_words_are_not_a_new_body_heuristic():
    # Only an explicit title badge or structured closure fact is added here.
    facts=api_facts(support_summary='지난해 모집은 마감되었습니다. 올해는 예비창업자 MVP 제작과 사업화 지원을 계속 모집합니다.')
    assert actionability(facts,AT)==(True,'PREANNOUNCEMENT')
    assert candidate_decision(facts,AT)==(True,'SEVEN_DAY_WINDOW_LOST_IF_WAITING')
