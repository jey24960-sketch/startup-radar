"""Public source examples that were missed by the old relevance rules."""
import json
from pathlib import Path

import pytest

from radar.relevance import (CONDITIONAL, GFC_RELEVANT, OUT_OF_SCOPE,
                             PUBLISHABLE_STATUSES, REVIEW_REQUIRED, classify)


CASES = json.loads((Path(__file__).parent / 'fixtures' /
                    'relevance_omissions_20261027.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('source', CASES, ids=lambda row: row['title'])
def test_confirmed_omissions_have_recognised_startup_support(source):
    # These source facts are retained verbatim, including title spelling and the
    # Nexus support description whose concrete benefits occur after character 400.
    decision = classify(source)
    assert decision['relevance_status'] in PUBLISHABLE_STATUSES
    assert decision['startup_leverage'] == 'HIGH'


@pytest.mark.parametrize('title', ['화요IR 참여기업 모집', '글로벌IR 발표 참가팀 모집',
                                  '스타트업 IR데모데이 참가팀 모집'])
def test_ir_may_touch_korean_words(title):
    assert classify({'title': title})['relevance_status'] in PUBLISHABLE_STATUSES


@pytest.mark.parametrize('title', ['FIRST 프로그램 참여자 모집', 'VIRTUAL 프로그램 모집',
                                  '기업 AIR 시스템 지원사업'])
def test_ir_is_not_an_infix_in_an_english_word(title):
    decision = classify({'title': title})
    assert not any(x['label'] == '투자 매칭·IR·데모데이'
                   for x in decision['evidence']['core_startup'])


def test_climate_technology_does_not_mean_a_review_story():
    decision = classify({'title': '기후기술 예비창업자 전문가 멘토링 모집'})
    assert decision['relevance_status'] == GFC_RELEVANT
    assert decision['evidence']['event_soft'] == []


@pytest.mark.parametrize('title', ['창업 참여후기 공유 행사', '창업 프로그램 후기 공유',
                                  '스타트업 성공 사례 공유 특강'])
def test_actual_review_and_success_story_events_remain_out_of_scope(title):
    assert classify({'title': title})['relevance_status'] == OUT_OF_SCOPE


def test_guarantee_institution_is_not_a_guarantee_product():
    facts = {'title': '예비창업자 창업학교 교육생 모집',
             'support_summary': '충남신용보증재단에서 예비창업자의 창업 실무교육을 지원합니다.'}
    assert classify(facts)['relevance_status'] in PUBLISHABLE_STATUSES
    assert classify({'title': '중소기업 신용보증 및 보증료 지원'})['relevance_status'] == OUT_OF_SCOPE


def test_late_support_and_applicant_restrictions_are_not_cut_off():
    row = {'title': 'Nexus Connect 프로그램 참여기업 모집',
           'applicant_summary': ('신청에 필요한 일반 안내입니다. ' * 50) + '서울시 소재 기업',
           'support_summary': ('프로그램 운영과 참여절차에 관한 안내입니다. ' * 50) +
                              '선정팀 액셀러레이팅과 투자 연계를 지원합니다.'}
    decision = classify(row)
    assert decision['relevance_status'] == CONDITIONAL
    assert '서울시 소재 기업' in decision['restriction_summary']


def test_a_tenant_in_a_shop_is_not_assumed_to_be_a_startup_incubatee():
    decision = classify({'title': '복합 쇼핑몰 입점자 모집'})
    assert decision['relevance_status'] == OUT_OF_SCOPE


def test_startup_jobs_and_incumbent_factory_support_remain_out_of_scope():
    assert classify({'title': '스타트업 MVP 제작 인턴 모집',
                     'support_summary': '인턴으로 참여해 프로토타입을 제작합니다.'})['relevance_status'] == OUT_OF_SCOPE
    assert classify({'title': '지역 제조공정 개선 지원사업',
                     'support_summary': '기존 제조기업의 실증 및 설비 개선을 지원합니다.'})['relevance_status'] == OUT_OF_SCOPE


def test_uncertain_startup_candidate_is_distinct_from_a_confirmed_opportunity():
    decision = classify({'title': '혁신 스타트업 지원 프로그램 모집',
                         'applicant_summary': '서울시 소재 창업기업'})
    assert decision['relevance_status'] == REVIEW_REQUIRED
    assert decision['startup_leverage'] == 'UNKNOWN'
    assert decision['restriction_summary'] == '서울시 소재 기업'
    assert '확인 필요' in decision['startup_leverage_reason']
