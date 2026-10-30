from copy import deepcopy

import pytest

from radar.publication_reviews import apply_reviews, reviewed_classification, _compatible_source_versions


def candidate():
    return {'program_id': 'p', 'version_id': 'v1', 'snapshot': {
        'title': '원문 제목', 'support_summary': '페이지 전체', 'review_note': '미확인',
        'application_end_at': '2026-11-15T00:00:00+09:00'}}


def review(disposition='RETAIN'):
    return {'program_id': 'p', 'reviewed_version_id': 'v1', 'active': True,
            'disposition': disposition, 'snapshot_patch': {'support_summary': '시제품 제작'},
            'relevance_status': 'CONDITIONAL', 'restriction_summary': '서울 소재 기업',
            'reason': '수행기관의 공식 공고 자격과 지원내용 확인'}


def test_corrections_apply_only_to_reviewed_version_without_mutating_source():
    row = candidate()
    before = deepcopy(row)
    rows, withheld = apply_reviews([row], [review()])
    assert row == before
    assert rows[0]['snapshot']['support_summary'] == '시제품 제작'
    assert 'review_note' not in rows[0]['snapshot']
    assert rows[0]['snapshot']['application_end_at'] == before['snapshot']['application_end_at']
    assert withheld == {}
    decision = reviewed_classification(rows[0], {'evidence': {}, 'relevance_status': 'GFC_RELEVANT'})
    assert decision['relevance_status'] == 'CONDITIONAL'
    assert decision['restriction_summary'] == '서울 소재 기업'
    row['version_id'] = 'v2'
    rows, _ = apply_reviews([row], [review()])
    assert rows[0] == row


@pytest.mark.parametrize('disposition', ['HOLD', 'EXCLUDE', 'DUPLICATE'])
def test_held_excluded_and_verified_duplicates_do_not_reappear_on_reingestion(disposition):
    row = candidate()
    row['version_id'] = 'v2'
    rows, withheld = apply_reviews([row], [review(disposition)])
    assert rows == []
    assert withheld == {'REVIEWED_' + disposition: 1}
    released = review(disposition) | {'active': False}
    assert apply_reviews([row], [released]) == ([row], {})


def test_reviews_cannot_bypass_dates_or_change_identity():
    for field in ('application_end_at', 'official_url', 'title'):
        invalid = review() | {'snapshot_patch': {field: 'changed'}}
        with pytest.raises(ValueError, match='descriptive facts'):
            apply_reviews([candidate()], [invalid])


def source_version(**updates):
    return {'id': 'v1', 'program_id': 'p', 'raw_text': '공식 원문에 명시된 지원내용·신청대상',
            'normalized': {'title': '공고', 'organization': '소관부처',
                'support_summary': '기존 파서 전체본문', 'applicant_summary': '중소기업',
                'application_end_at': '2026-11-15T00:00:00+09:00', 'official_url': 'https://example.org/1'},
            'source_operators': {'source': {'excInsttNm': '수행기관', 'jrsdInsttNm': '소관부처'}}, **updates}


def test_reviewed_patch_survives_only_exact_evidence_parser_versions():
    old = source_version()
    current = source_version(id='v2', normalized=old['normalized'] | {
        'organization': '수행기관', 'support_summary': '새 파서 추출 지원내용', 'applicant_summary': '실제 신청자격'})
    assert _compatible_source_versions(old, current)
    row = candidate() | {'version_id': 'v2'}
    reviewed = review() | {'compatible_version_ids': ['v2']}
    kept, _ = apply_reviews([row], [reviewed])
    assert kept[0]['snapshot']['support_summary'] == '시제품 제작'
    assert kept[0]['snapshot']['application_end_at'] == row['snapshot']['application_end_at']
    future = row | {'version_id': 'v3'}
    assert apply_reviews([future], [reviewed])[0][0] == future


@pytest.mark.parametrize('change', [
    {'program_id': 'other'}, {'raw_text': ''}, {'raw_text': '공식 본문이 변경됨'},
    {'source_operators': {}},
    {'source_operators': {'another-source': {'excInsttNm': '수행기관'}}},
    {'source_operators': {'source': {'excInsttNm': '새 수행기관', 'jrsdInsttNm': '소관부처'}}},
])
def test_changed_or_missing_publisher_evidence_never_carries_review(change):
    assert not _compatible_source_versions(source_version(), source_version(id='v2', **change))


@pytest.mark.parametrize('field,value', [('title','새 공고'), ('official_url','https://example.org/2'),
    ('application_end_at','2026-11-16T00:00:00+09:00'), ('application_end_precision','DATETIME')])
def test_source_equivalence_cannot_carry_across_other_material_facts(field, value):
    old=source_version()
    new=source_version(id='v2',normalized=old['normalized'] | {field:value})
    assert not _compatible_source_versions(old,new)
