"""GFC Relevance v1.1 two-axis classification. No database required."""
import pytest
from radar.relevance import (CONDITIONAL, GFC_RELEVANT, OUT_OF_SCOPE, PUBLISHABLE_STATUSES,
                             RELEVANCE_VERSION, REVIEW_REQUIRED, classify)


def facts(title, applicant='', support=''):
    return {'title': title, 'applicant_summary': applicant, 'support_summary': support}


def status(title, applicant='', support=''):
    return classify(facts(title, applicant, support))['relevance_status']


def test_version_is_pinned():
    assert RELEVANCE_VERSION == 'gfc-v1.1'
    assert PUBLISHABLE_STATUSES == (GFC_RELEVANT, CONDITIONAL)


def test_broadly_accessible_accelerator_is_relevant():
    decision = classify(facts('2026년 초기창업기업 액셀러레이팅 배치 프로그램 참가팀 모집',
                              '예비창업자 및 창업 3년 이내 팀',
                              '6개월 액셀러레이팅, 멘토링, 데모데이 참여 기회를 제공합니다.'))
    assert decision['relevance_status'] == GFC_RELEVANT
    assert decision['startup_leverage'] == 'HIGH' and decision['applicability'] == 'BROAD'
    assert decision['restriction_summary'] is None
    assert decision['startup_leverage_reason']


@pytest.mark.parametrize('title,applicant', [
    ('바이오 스타트업 실증(PoC) 지원사업 참여기업 모집', '바이오·헬스케어 분야 창업기업'),
    ('[대전] 스타트업 투자연계 IR 프로그램 참여기업 모집', '대전 소재 기업'),
    ('오픈이노베이션 실증 프로그램 참여 스타트업 모집', 'Pre-A ~ Series A 투자 유치 기업'),
    ('글로벌 진출 액셀러레이팅 참가기업 모집', '사업자등록증 보유 기업만 신청 가능'),
])
def test_high_leverage_but_restricted_is_conditional(title, applicant):
    decision = classify(facts(title, applicant))
    assert decision['relevance_status'] == CONDITIONAL
    assert decision['startup_leverage'] == 'HIGH' and decision['applicability'] == 'RESTRICTED'
    # A member must see the restriction without opening the official notice.
    assert decision['restriction_summary']


@pytest.mark.parametrize('title', [
    '[울산] 중구 2026년 소상공인 카드수수료 지원사업 추가모집 공고',
    '[경기] 광명시 2026년 하반기 착한가격업소 신규 모집 공고',
    '2026년 소상공인 경영안정자금 융자 지원 공고',
    '중소기업 근로자 임차료 및 공과금 지원 공고',
    '2026년 가족친화인증 기업 모집 공고',
    '직무발명보상 우수기업 인증 신청 안내',
    '2026년 뿌리기업 맞춤형 제조로봇 공정연구 지원대상기업 모집',
    '철강산업 전환성장을 위한 사업재편 컨설팅 지원사업 모집',
    '2026년 우수기업 표창 대상자 추천 공고',
    '지역 사회적경제 장터 참여기업 추가모집 공고',
])
def test_merchant_administrative_and_mature_industry_support_is_out_of_scope(title):
    decision = classify(facts(title))
    assert decision['relevance_status'] == OUT_OF_SCOPE
    assert decision['startup_leverage'] == 'LOW'


@pytest.mark.parametrize('title', [
    '2026년 SVC Seoul 인턴십 프로그램 학생인턴 모집공고',
    '2026년 대학생 서포터즈 모집 공고',
    '연구원 채용 공고',
])
def test_employment_and_internship_postings_are_out_of_scope(title):
    assert status(title) == OUT_OF_SCOPE


def test_generic_success_lecture_is_not_automatically_relevant():
    # A founder's fundraising war story is not a fundraising program.
    assert status('대학생 창업자가 투자를 유치하며 겪었던 이야기들 - 제9차 벤처스타트업 아카데미 특강',
                  '', '선배 창업가의 성공 사례를 공유하는 특강입니다.') == OUT_OF_SCOPE
    assert status('창업 성공사례 공유 네트워킹 세미나') == OUT_OF_SCOPE


def test_event_with_a_concrete_founder_deliverable_can_pass():
    assert status('창업팀 대상 고객 발굴 워크숍 및 MVP 제작 지원 프로그램 참가팀 모집',
                  '', 'MVP 프로토타입 제작과 고객 검증을 수행합니다.') in PUBLISHABLE_STATUSES


def test_startup_legal_and_equity_support_is_publishable():
    decision = classify(facts('스타트업 주주간 계약 및 투자계약 법률지원 프로그램 참여기업 모집',
                              '창업 7년 이내 기업'))
    assert decision['relevance_status'] in PUBLISHABLE_STATUSES
    # Generic SME compliance advice is not the same thing.
    assert status('중소기업 안전보건 법정의무 이행 컨설팅 지원') == OUT_OF_SCOPE


@pytest.mark.parametrize('title', [
    '2026년 중소기업 지원사업 통합 공고',
    '대학생 대상 프로그램 참여자 모집 안내',
    '청년 지원사업 신청 안내',
    'AI 활용 중소기업 지원 공고',
    '글로벌 스타트업 지원사업 안내',
])
def test_audience_words_alone_are_not_evidence_of_relevance(title):
    # 중소기업 / 대학생 / 청년 / AI / 글로벌 / 스타트업 describe who may apply,
    # not what the program lets a founder do.
    assert status(title) != GFC_RELEVANT


def test_early_stage_window_is_the_audience_not_a_restriction():
    # "창업 3년 이내" includes GFC members; "업력 7년 이상" excludes them.
    assert status('초기창업기업 액셀러레이팅 참가팀 모집', '창업 3년 이내 기업') == GFC_RELEVANT
    assert status('액셀러레이팅 참가기업 모집', '업력 7년 이상 기업') == CONDITIONAL


def test_low_leverage_with_a_narrow_restriction_stays_out_of_scope():
    # Restriction must never upgrade a weak program into CONDITIONAL.
    decision = classify(facts('[부산] 2026년 조선기자재 제조공정 개선 지원사업 참여기업 모집',
                              '부산 소재 조선업 제조기업'))
    assert decision['relevance_status'] == OUT_OF_SCOPE
    assert decision['startup_leverage'] == 'LOW'


def test_english_investor_programme_titles_are_recognised():
    # Korean programme titles routinely use English for the investor track.
    assert status('2026 강원권 LIPS 민간운영사 연합 INVESTOR DAY 참여기업 모집') in PUBLISHABLE_STATUSES
    assert status('스타트업 Pitching Day 참가팀 모집') in PUBLISHABLE_STATUSES


@pytest.mark.parametrize('title,applicant', [
    ('[경남] 창원시 제조 디지털전환(DX) 확산기술 지원사업 모집', '지역 제조기업'),
    ('[경남] 의료기기 부품ㆍ모듈 국산화 및 기술개발 지원사업 공고', '부품 제조기업'),
    ('[경북] 전기차 규제자유특구 특구사업자 책임보험료 지원 공고', '특구 사업자'),
])
def test_incumbent_manufacturer_upgrades_do_not_reach_members(title, applicant):
    # These mention 실증/사업화 in passing but are operating support for
    # established factories, so they must not surface as CONDITIONAL.
    assert classify(facts(title, applicant))['relevance_status'] not in PUBLISHABLE_STATUSES


def test_conflicting_signals_are_held_for_operator_review():
    decision = classify(facts('소상공인 카드수수료 지원 및 액셀러레이팅 배치 프로그램 모집'))
    assert decision['relevance_status'] == REVIEW_REQUIRED
    assert decision['evidence']['conflict'] is True


def test_evidence_thin_notice_is_held_rather_than_judged():
    decision = classify(facts('모집'))
    assert decision['relevance_status'] == REVIEW_REQUIRED
    assert decision['evidence']['thin_text'] is True


def test_review_required_is_never_member_facing():
    assert REVIEW_REQUIRED not in PUBLISHABLE_STATUSES
    assert OUT_OF_SCOPE not in PUBLISHABLE_STATUSES


def test_generic_trade_fair_participation_is_out_of_scope_but_startup_entry_is_not():
    assert status('[서울] 2026년 홍콩 메가쇼 참가기업 모집 공고',
                  '', '해외 전시회 참가 부스 및 판로개척을 지원합니다.') == OUT_OF_SCOPE
    assert status('베트남 테크페스트 K-스타트업 통합관 참가기업 모집 공고',
                  '창업기업', '현지 투자자 및 바이어 매칭과 해외 진출을 지원합니다.') in PUBLISHABLE_STATUSES


def test_classification_never_mutates_source_facts():
    row = facts('예비창업자 액셀러레이팅 모집', '대상', '내용')
    before = dict(row)
    classify(row)
    assert row == before
