from radar.models import Program
from radar.official_facts import clean_legacy_snapshot
from radar.weekly import publication_fingerprint, snapshot


def legacy():
    return {
        'title': '예비 창업팀 고객 검증 프로그램',
        'organization': '창업재단',
        'official_url': 'https://example.org/notice/1',
        'applicant_summary': '예비창업가 또는 법인 3년 이내',
        'support_summary': '고객 검증 창업교육\n공식 공고 상세\n반복 제목\n지원내용\n무료 멘토링과 고객 인터뷰\n문의처\n02-0000-0000',
    }


def test_cleaning_legacy_source_dump_does_not_make_an_unchanged_opportunity_an_update():
    before = legacy()
    after = clean_legacy_snapshot(before)
    assert '공식 공고 상세' not in after['support_summary']
    assert '무료 멘토링과 고객 인터뷰' in after['support_summary']
    assert publication_fingerprint(before) == publication_fingerprint(after)
    after['application_end_at'] = '2026-12-01T23:59:00+09:00'
    assert publication_fingerprint(before) != publication_fingerprint(after)


def test_stored_normalized_programs_project_clean_public_fields_without_mutating_evidence():
    facts = legacy()
    program = Program.model_validate(facts)
    public = snapshot(program, {})
    assert '공식 공고 상세' not in public['support_summary']
    assert '02-0000-0000' not in public['support_summary']
    assert program.support_summary == facts['support_summary']


def test_board_return_page_does_not_republish_an_unchanged_notice():
    before = clean_legacy_snapshot(legacy())
    before['official_url'] = 'https://venture.yonsei.ac.kr/community/notice/342?p=2'
    after = {**before, 'official_url': 'https://venture.yonsei.ac.kr/community/notice/342?p=5'}
    assert publication_fingerprint(before) == publication_fingerprint(after)
    assert snapshot(Program.model_validate(before), {})['official_url'].endswith('/342')
    after['official_url'] = 'https://venture.yonsei.ac.kr/community/notice/343?p=5'
    assert publication_fingerprint(before) != publication_fingerprint(after)
