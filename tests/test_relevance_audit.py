"""Regressions from the October 27 full manual audit, including valid neighbours.

The closed UNIST notice (#87) is a valid startup subject; the separate date
actionability gate excludes it. It must not become a thematic title blacklist.
"""
import json
from pathlib import Path

import pytest

from radar.relevance import (CONDITIONAL, GFC_RELEVANT, OUT_OF_SCOPE,
                             PUBLISHABLE_STATUSES, classify)


AUDIT_CASES = json.loads((Path(__file__).parent / 'fixtures' /
                         'relevance_audit_20261027.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('row', AUDIT_CASES, ids=lambda row: str(row['number']))
def test_reviewed_program_purposes_and_valid_neighbours(row):
    decision = classify(row)
    assert decision['relevance_status'] == row['expected_status']
    assert decision['restriction_summary'] == row['expected_restriction']


@pytest.mark.parametrize('title,applicant,support', [
    ('G밸리 의료기기 FDA 글로벌 교육 참여자 모집', '의료기기 분야 예비창업자',
     '해외 규격 인증을 준비하는 창업자를 위한 실무교육과 해외 진출 지원'),
    ('창업팀 고객 검증 워크숍 참가팀 모집', '예비창업팀', '고객 인터뷰와 MVP 제작을 수행합니다.'),
    ('스타트업 투자교류회 참가기업 모집', 'AC/VC 및 초기 창업기업', '스타트업 IR 발표와 투자 매칭'),
    ('해외 시장진출 참가기업 모집', '초기 창업기업', '현지 바이어 매칭과 PoC 수행을 지원합니다.'),
    ('전략기술 딥테크 시제품 제작 지원기업 모집', '울산 소재 예비창업팀', '프로토타입 제작 지원'),
])
def test_exclusions_preserve_practical_founder_tracks(title, applicant, support):
    assert classify(dict(title=title, applicant_summary=applicant,
                         support_summary=support))['relevance_status'] in PUBLISHABLE_STATUSES


@pytest.mark.parametrize('title,applicant,support,restriction', [
    ('[온라인·무료] 예비창업자 실행 교육 모집', '사업자 등록 필요 없음, 분야 무관 예비창업자',
     '시제품 제작 과제 수행', None),
    ('[한국어촌어항공단] 창업 아이디어 공모', '전국 청년 누구나',
     '바이오 창업기업 대표의 경험담을 참고해 아이디어 공모에 참여', None),
    ('[모집공고] 예비창업팀 시제품 제작 지원', '예비창업팀', '', None),
    ('캠퍼스 액셀러레이팅 모집', '분야 무관 학생창업팀',
     'D2SF 바이오·헬스케어 기업 투자 사례와 반도체 창업기업 사례 소개', None),
    ('[충남] 액셀러레이팅 프로그램 모집', '도내 소재 기업', '', '충남 소재 기업'),
    ('[충남] 액셀러레이팅 프로그램 모집', '전국 예비창업팀 누구나', '', None),
    ('액셀러레이팅 모집', '충청남도 내 창업 예정인 예비창업팀 또는 충청남도 소재 기업', '',
     '충청남도 소재·이전·창업 예정 조건'),
    ('액셀러레이팅 모집', '개인, 팀, 기업 누구나\n호남지역 소재 기업 가점', '', None),
    ('액셀러레이팅 모집', '법인 설립 필수 아님\n수출 실적 우대', '', None),
    ('액셀러레이팅 모집', '만 40세 이상 예비창업자', '', '중장년 연령 조건'),
    ('액셀러레이팅 모집', '전체', '신청대상: 반도체 분야 창업기업', '특정 산업 분야 한정'),
    ('액셀러레이팅 모집', '분야 무관 창업팀', '☞ 기업당 최대 5천만원 사업화 지원', None),
])
def test_only_actual_mandatory_audience_facts_make_badges(title, applicant, support, restriction):
    decision = classify(dict(title=title, applicant_summary=applicant, support_summary=support))
    assert decision['relevance_status'] == (CONDITIONAL if restriction else GFC_RELEVANT)
    assert decision['restriction_summary'] == restriction


def test_excluded_program_is_not_rescued_by_incidental_startup_words():
    decision = classify(dict(title='중소기업 글로벌 온라인몰 입점 지원',
                             applicant_summary='초기창업기업도 신청 가능',
                             support_summary='스타트업 제품의 판매를 위한 입점과 해외 진출 지원'))
    assert decision['relevance_status'] == OUT_OF_SCOPE
    assert decision['evidence']['curation_exclusion']
