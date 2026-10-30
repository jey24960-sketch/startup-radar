"""Member descriptions stay separate from cached complete source evidence."""
import json
from pathlib import Path

from radar.official_facts import clean_legacy_snapshot, public_detail_fields, apply_evidence
from radar.relevance import classify, GFC_RELEVANT, CONDITIONAL
from test_official_facts import program


LEGACY = json.loads((Path(__file__).parent / 'fixtures' / 'running_mate_9_legacy.json').read_text(encoding='utf-8'))


def test_running_mate_retains_real_support_and_advice_without_page_chrome():
    result = clean_legacy_snapshot(LEGACY)
    assert '무료' in result['support_summary']
    assert '5주간 프로그램 구성' in result['support_summary']
    assert '피어피드백' in result['support_summary']
    assert '서비스 바우처' in result['support_summary']
    assert '사업안내 바로가기' not in result['support_summary']
    assert '담당부서' not in result['support_summary']
    assert '공식 공고 상세' not in result['support_summary']
    assert '연락처' not in result['support_summary']
    assert result['applicant_summary'].count('극초기 창업팀') == 1
    assert '별도 신청 제한은 없으나' in result['applicant_summary']
    assert '권장' in result['applicant_summary']
    assert classify(result)['relevance_status'] == GFC_RELEVANT
    assert classify(result)['restriction_summary'] is None
    assert clean_legacy_snapshot(result) == result
    assert '공식 공고 상세' in LEGACY['support_summary']


def test_new_evidence_never_appends_the_whole_page_or_repeats_sections():
    detail = LEGACY['support_summary'].split('공식 공고 상세', 1)[1]
    p = program(title=LEGACY['title'], support_summary=LEGACY['support_summary'].split('공식 공고 상세', 1)[0].strip(),
                applicant_summary=LEGACY['applicant_summary'])
    item = {'status': 'SUCCESS', 'text': detail}
    result = apply_evidence(p, item)
    assert result.support_summary == clean_legacy_snapshot(LEGACY)['support_summary']
    assert apply_evidence(result, item) == result
    assert item['text'] == detail


def test_unknown_layout_preserves_api_summary_and_leaves_detail_as_evidence():
    p = program()
    item = {'status': 'SUCCESS', 'text': '제목\n메뉴\n지원기관\n임의 페이지 전체 내용'}
    assert apply_evidence(p, item).support_summary == p.support_summary
    assert clean_legacy_snapshot({'support_summary': '일반 설명 속 공식 공고 상세 문구'}) == {
        'support_summary': '일반 설명 속 공식 공고 상세 문구'}


def test_labelled_inline_fields_do_not_absorb_contacts_and_application_dates():
    fields = public_detail_fields('지원내용: MVP 제작\n신청대상 : 예비창업팀\n제외대상\n없음\n'
                                  '신청기간\n2026.10.01 ~ 2026.11.01\n문의처\n담당자 연락처')
    assert fields == {'support_summary': 'MVP 제작', 'applicant_summary': '예비창업팀\n제외대상\n없음'}


def test_industry_restrictions_need_a_scoped_audience_not_an_incidental_word():
    base = {'title': '예비창업자 액셀러레이팅 참여팀 모집', 'applicant_summary': '분야 무관 예비창업자'}
    for text in ('바이오 분야 전문가 멘토링을 제공합니다.',
                 '반도체 전문 투자사에서 멘토로 참여합니다.',
                 '한국관광공사에서 창업기업의 사업화를 지원합니다.'):
        result = classify({**base, 'support_summary': text})
        assert result['relevance_status'] == GFC_RELEVANT
    for applicant in ('바이오·헬스케어 분야 창업기업', '반도체 분야에서 투자를 희망하는 국내 창업기업',
                      '바이오 분야 스타트업만 신청 가능하며, 지역 제한은 없습니다.',
                      '바이오 분야 창업기업이며 지역 제한은 없습니다.'):
        result = classify({**base, 'applicant_summary': applicant})
        assert result['relevance_status'] == CONDITIONAL
        assert result['restriction_summary'] == '특정 산업 분야 한정'


def test_contact_and_footer_headings_stop_public_support_text():
    fields = public_detail_fields('지원내용\n무료 창업교육\n담당자\n홍길동 02-000-0000\n개인정보 처리방침\n이용약관')
    assert fields == {'support_summary': '무료 창업교육'}
