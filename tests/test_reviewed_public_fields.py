"""Audited real source bodies: public benefits, audience and performing body."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from radar.adapters.base import Candidate, AcquiredDetail
from radar.adapters.official import BizInfoApiAdapter
from radar.adapters.weekly_direct import OfficialChannelAdapter
from radar.official_facts import public_detail_fields, direct_public_fields, apply_evidence
from test_official_facts import program

ROOT = Path(__file__).resolve().parents[1]
CASES = {r['number']: r for r in json.loads((ROOT/'tests/fixtures/reviewed_public_fields_20261030.json').read_text(encoding='utf-8'))}
SOURCES = {s['slug']: s for s in json.loads((ROOT/'weekly-direct-sources.json').read_text(encoding='utf-8'))}


@pytest.mark.parametrize('number', [5, 9, 31, 123, 124])
def test_direct_normalizer_does_not_publish_no_marker_full_pages(number):
    row = CASES[number]
    source = SOURCES[row['source_slug']]
    candidate = Candidate(source['slug'], 'fixture', row['url'], row['url'], row['title'])
    detail = AcquiredDetail(row['url'], row['text'], row['title'])
    result = OfficialChannelAdapter(source, Mock()).normalize(candidate, detail, [])
    assert result.support_summary and len(result.support_summary) < len(row['text'])/2
    assert not any(token in result.support_summary for token in ('이전글', '다음글', '#해시태그', '#의료기기', '#인력', '스크랩', 'Copyright', 'allure620@'))
    assert detail.text == row['text']  # Complete source evidence is unchanged.
    if number == 5:
        assert '700만 원' in result.support_summary
        assert '특수대학원' in result.applicant_summary and '제외' in result.applicant_summary
        assert '2인 이상' in result.applicant_summary
    if number == 9:
        assert '멘토링' in result.support_summary and '해외진출' in result.support_summary
        assert '예비창업자 지원 불가' in result.applicant_summary
        assert '운영 기간' not in result.applicant_summary
    if number == 124:
        assert result.organization == '한국과학기술연구원'
        assert result.applicant_summary == '서울 내 본사 혹은 지사를 두고 있는 의료기기 및 디지털헬스케어 기업'
    if number == 123:
        assert result.organization == '고양산업진흥원'


def test_lgd_track_repetitions_are_source_facts_not_duplicate_lines():
    fields = public_detail_fields(CASES[80]['text'])
    support = fields['support_summary']
    assert support.count('2. PoC 지원금: 기업당 최대 5,000만원') == 2
    assert support.count('3. 액셀러레이팅:') == 2
    assert support.count('4. 후속지원 협력') == 2
    assert support.index('[Display 부문]') < support.index('[신사업 부문]')
    p = program(official_url=CASES[80]['url'], support_summary='공식 프로그램 소개')
    item = {'status': 'SUCCESS', 'text': CASES[80]['text']}
    enriched = apply_evidence(p, item)
    assert enriched.support_summary.count('2. PoC 지원금: 기업당 최대 5,000만원') == 2
    assert apply_evidence(enriched, item) == enriched


def test_d2sf_support_package_does_not_import_alumni_industries_or_faq():
    row = CASES[73]
    fields = direct_public_fields(row['text'], row['title'], row['source_slug'])
    support = fields['support_summary']
    assert '개발 자금 1천만 원' in support
    assert '500만 원' in support
    assert 'Claude' in support
    assert '투자 연계' in support
    assert '헬스케어' not in support and '52팀' not in support and '김대식' not in support
    assert '자주 묻는 질문' not in support
    assert '법인 설립 여부에 관계 없이' in fields['applicant_summary']


@pytest.mark.parametrize('number', [2, 25, 121, 122])
def test_bizinfo_api_uses_performer_and_real_stated_audience(number):
    row = CASES[number]
    raw = deepcopy(row['api'])
    candidate = Candidate('bizinfo', 'fixture', row['url'], row['url'], row['title'], raw)
    adapter = BizInfoApiAdapter({'slug': 'bizinfo', 'name': '기업마당', 'config': {}}, Mock())
    result = adapter.normalize(candidate, AcquiredDetail(row['url'], '', row['title']), [])
    assert result.organization == raw['excInsttNm']
    assert result.organization != raw['jrsdInsttNm']
    assert result.applicant_summary not in ('중소기업', '창업벤처')
    assert raw == row['api']
    if number == 25:
        assert '광역자치단체' in result.applicant_summary
    if number == 122:
        assert '팀 참가 불가' in result.applicant_summary
        assert '일반부문' in result.applicant_summary and '기업부문' in result.applicant_summary


def test_unknown_direct_layout_stays_unknown_instead_of_copying_page():
    assert direct_public_fields('메뉴\n게시일\n알 수 없는 구조의 공고\n문의처\n02-000-0000') == {}


def test_generic_api_target_is_replaced_by_explicit_multiline_audience():
    p = program(applicant_summary='중소기업')
    item = {'status': 'SUCCESS', 'text': '지원내용\n무료 시제품 제작\n신청대상\n예비창업자 또는 3년 이내 기업\n제외대상\n등록 후 3년 초과 기업\n문의처\n연락처'}
    result = apply_evidence(p, item)
    assert result.applicant_summary.startswith('예비창업자 또는 3년 이내 기업')
    assert '3년 초과' in result.applicant_summary
    assert '중소기업' not in result.applicant_summary


def test_numbered_education_attributes_do_not_drop_the_rest_of_the_curriculum():
    fields = public_detail_fields('교육안내\n1. 진행방식 : Zoom\n2. 참가비 : 무료\n3. 소요시간 : 1시간 30분\n4. 강의내용 : IR피칭\n문의처\n이메일')
    assert '무료' in fields['support_summary']
    assert '1시간 30분' in fields['support_summary']
    assert 'IR피칭' in fields['support_summary']
    assert '이메일' not in fields['support_summary']


def test_explicit_crossposted_host_is_used_instead_of_the_board_owner():
    fields = direct_public_fields('교외 프로그램\n주최: 한국어촌어항공단\n참가대상: 만 19~39세\n시상내역: 총 상금 1500만원\n이전글\n다른 공고')
    assert fields['organization'] == '한국어촌어항공단'
    assert fields['support_summary'] == '총 상금 1500만원'


def test_generic_local_government_category_uses_only_explicit_named_actor():
    raw={'excInsttNm':'기초자치단체','jrsdInsttNm':'충청남도','trgetNm':'중소기업',
         'bsnsSumryCn':'청양군에서는 청년창업공간 운영지원을 하고 있습니다.\n☞ 미창업 청년\n☞ 창업공간 6개월 지원'}
    candidate=Candidate('bizinfo','fixture','https://www.bizinfo.go.kr/notice','https://www.bizinfo.go.kr/notice','창업공간 모집',raw)
    adapter=BizInfoApiAdapter({'slug':'bizinfo','name':'기업마당','config':{}},Mock())
    result=adapter.normalize(candidate,AcquiredDetail(candidate.official_detail_url,'',candidate.title),[])
    assert result.organization=='청양군'
