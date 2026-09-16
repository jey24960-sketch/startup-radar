"""GFC Stage Fit v1.0 classifier. No database required."""
import pytest
from radar.relevance import classify as classify_relevance
from radar.stage import LABELS, MAX_STAGES, STAGE_VERSION, STAGES, classify_stage, labels_for, telegram_tag


def facts(title, support='', applicant=''):
    return {'title': title, 'support_summary': support, 'applicant_summary': applicant}


def codes(title, support='', applicant=''):
    return classify_stage(facts(title, support, applicant))['stage_codes']


def test_exactly_five_official_stages_with_exact_korean_labels():
    assert STAGE_VERSION == 'gfc-stage-v1.0'
    assert [label for _, label in STAGES] == ['아이디어 전', '팀 구성·아이디어', '랜딩·시장검증', 'MVP·PoC', '사업자·법인 이후']
    assert MAX_STAGES == 2


def test_problem_discovery_bootcamp_is_pre_idea():
    assert codes('창업 입문 부트캠프: 문제 발굴부터 시작하는 첫 걸음', '문제 정의와 아이디어 발굴 워크숍') == ['STAGE_0']


def test_ideathon_and_team_building_is_team_idea_stage():
    assert codes('2026 GFC 아이디어톤 참가팀 모집', '팀 빌딩과 아이디어 고도화를 지원합니다') == ['STAGE_1']


def test_customer_validation_and_landing_experiments_are_market_validation():
    assert codes('고객 검증 스프린트: 랜딩 페이지로 수요 테스트', '초기 고객 인터뷰와 시장 검증을 수행합니다') == ['STAGE_2']


def test_mvp_grant_and_poc_pilot_are_mvp_poc():
    assert codes('MVP 제작 지원사업 참가팀 모집', '프로토타입 제작비를 지원합니다') == ['STAGE_3']
    assert codes('스마트시티 PoC 실증 파일럿 참여기업 모집', '실증 환경과 파일럿 운영을 지원합니다') == ['STAGE_3']


def test_open_innovation_for_operating_startup_spans_mvp_and_post_incorporation():
    decision = classify_stage(facts('대기업 오픈이노베이션 PoC 프로그램 참여 스타트업 모집',
                                    '제품 실증(PoC)과 공동 사업화를 진행합니다'))
    assert decision['stage_codes'] == ['STAGE_3', 'STAGE_4']
    assert decision['stage_labels'] == ['MVP·PoC', '사업자·법인 이후']


def test_vc_investment_and_global_expansion_for_established_startups_is_post_incorporation():
    assert codes('글로벌 진출 스케일업 프로그램 참여기업 모집', 'VC 투자 유치와 해외 바이어 매칭을 지원합니다') == ['STAGE_4']


def test_incorporation_support_is_not_post_incorporation():
    # Helping a student founder incorporate is early operations, not "after".
    decision = classify_stage(facts('☆2026 학생창업 법인설립·사업장 주소지 제공 프로그램(~11.30 모집)☆',
                                    '법인 설립 절차와 사업장 주소지를 제공합니다'))
    assert 'STAGE_4' not in decision['stage_codes']
    assert decision['stage_codes'] == ['STAGE_3']


def test_corporation_required_is_a_restriction_and_never_sets_stage_by_itself():
    # Same programme text, with and without an eligibility clause: identical stage.
    base = facts('MVP 제작 지원 프로그램', '프로토타입 제작을 지원합니다')
    restricted = facts('MVP 제작 지원 프로그램', '프로토타입 제작을 지원합니다', '법인사업자만 신청 가능 · 매출 10억 이상 · 투자 유치 기업')
    assert classify_stage(base)['stage_codes'] == classify_stage(restricted)['stage_codes'] == ['STAGE_3']
    # And an eligibility clause alone yields nothing.
    assert codes('참여기업 모집', '', '법인사업자만 신청 가능') == []


def test_generic_entrepreneurship_lecture_does_not_overclaim():
    assert codes('창업가 초청 특강', '선배 창업가의 이야기를 듣습니다') == []


@pytest.mark.parametrize('title', ['대학생 대상 프로그램 참여자 모집', '글로벌 스타트업 지원사업 안내',
                                   '청년 창업기업 대상 안내', 'AI 중소기업 참여기업 모집'])
def test_audience_words_alone_do_not_determine_stage(title):
    assert codes(title) == []


def test_global_alone_is_not_a_stage_but_global_market_entry_is():
    assert codes('글로벌 창업 특강') == []
    assert codes('글로벌 진출 프로그램 참여기업 모집', '해외 법인 설립과 현지 파트너 매칭') == ['STAGE_4']


def test_never_more_than_two_stages_and_ordered_by_stage():
    decision = classify_stage(facts('아이디어톤 · MVP 제작 · 오픈이노베이션 · 투자 유치 총망라 프로그램',
                                    '팀 빌딩, 프로토타입 제작, 대기업 협업, VC 투자 매칭을 모두 지원합니다'))
    assert len(decision['stage_codes']) <= 2
    assert decision['stage_codes'] == sorted(decision['stage_codes'])


def test_labels_and_telegram_tag_never_expose_codes_or_invent_labels():
    assert labels_for(['STAGE_3', 'STAGE_4']) == ['MVP·PoC', '사업자·법인 이후']
    assert labels_for(['STAGE_9', None]) == []
    assert telegram_tag(['STAGE_3']) == '[MVP·PoC]'
    assert telegram_tag(['STAGE_3', 'STAGE_4']) == '[MVP·PoC / 사업자·법인 이후]'
    assert telegram_tag([]) == '' and telegram_tag(None) == ''
    assert 'STAGE_' not in telegram_tag(['STAGE_3'])


@pytest.mark.parametrize('title,applicant,stage', [
    ('초기창업기업 액셀러레이팅 참가팀 모집', '', 'STAGE_3'),
    ('오픈이노베이션 투자 유치 프로그램', '', 'STAGE_4'),
    ('바이오 스타트업 MVP 실증 지원', '바이오 분야 기업', 'STAGE_3'),
    ('[대전] 투자자 매칭 데모데이', '대전 소재 기업', 'STAGE_4'),
])
def test_stage_is_independent_of_relevance(title, applicant, stage):
    row = facts(title, '', applicant)
    relevance = classify_relevance(row)['relevance_status']
    assert relevance in ('GFC_RELEVANT', 'CONDITIONAL')
    assert stage in classify_stage(row)['stage_codes']
    # Neither classifier mutates the other's input or reads the other's output.
    assert classify_relevance(row)['relevance_status'] == relevance


def test_classification_never_mutates_facts():
    row = facts('MVP 제작 지원', '프로토타입', '누구나')
    before = dict(row)
    classify_stage(row)
    assert row == before


def test_tech_transfer_and_incubation_admission_count_as_initial_commercialisation():
    # Real calibration cases: tech transfer is initial commercialisation, and an
    # incubation admission notice is incubation even when phrased "입주 예비창업자".
    assert 'STAGE_3' in codes('12대 국가전략기술 분야 기술이전 수요 모집', '공공기술 기술이전·사업화를 지원합니다')
    assert 'STAGE_3' in codes('2026년 스타트업 96 입주 예비창업자 모집')


def test_overseas_exhibitions_and_country_specific_entry_are_market_entry():
    assert codes('[경기] 성남시 2026년 해외 전시회 개별 참가 지원 모집 공고', '해외 전시회 참가 비용을 지원합니다') == ['STAGE_4']
    assert 'STAGE_4' in codes('글로벌 스타트업 서밋 (일본) 밋업 참여기업 모집', '일본 진출을 희망하는 기업의 PoC와 파트너십을 지원합니다')
    assert 'STAGE_4' in codes('아시아 창업 엑스포 FLY ASIA 2026 참여 스타트업 모집', '1:1 밋업과 전시')
