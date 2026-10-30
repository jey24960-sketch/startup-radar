"""Date precision alone cannot defeat or establish cross-portal identity."""
from copy import deepcopy
import pytest
from radar.identity import deduplicate_publication, publication_identity_evidence
from radar.models import Program
from radar.weekly import snapshot, publication_fingerprint

TITLE='2026년 강원 특구 배치 프로그램 1기 참여기업 모집 공고'
ROUTE='https://forms.gle/NZP2VANG8peaduLz7'


def row(pid,portal,**changes):
    facts={'title':TITLE,'organization':'창업지원기관','official_url':f'https://{portal}.example/notice?id={pid}',
           'application_start_at':'2026-10-21T00:00:00+09:00','application_start_precision':'DATE',
           'application_end_at':'2026-11-11T23:59:59.999999+09:00','application_end_precision':'DATE',
           'identity_evidence':{'application_urls':[ROUTE]}}
    return {'program_id':pid,'snapshot':{**facts,**changes}}


def test_same_title_and_exact_route_allow_date_only_portal_to_agree_with_precise_publisher():
    coarse=row('coarse','portal-a')
    precise=row('precise','portal-b',application_start_at='2026-10-21T15:00:00+09:00',
                application_start_precision='DATETIME',application_end_at='2026-11-11T15:00:00+09:00',
                application_end_precision='DATETIME',applicant_summary='강원 특구 소재 또는 이전 예정 창업기업')
    original=deepcopy([coarse,precise])
    for rows in ([coarse,precise],[precise,coarse]):
        kept,dropped=deduplicate_publication(rows)
        assert [item['program_id'] for item in kept]==['precise']
        assert [(item['program_id'],item['duplicate_of']) for item in dropped]==[('coarse','precise')]
        assert kept[0]['snapshot']['application_end_at']=='2026-11-11T15:00:00+09:00'
    assert [coarse,precise]==original


def test_dates_compare_in_seoul_instead_of_string_or_utc_calendar_day():
    coarse=row('coarse','portal-a')
    precise=row('precise','portal-b',application_start_at='2026-10-20T16:00:00+00:00',
                application_start_precision='DATETIME',application_end_at='2026-11-11T06:00:00+00:00',
                application_end_precision='DATETIME')
    assert len(deduplicate_publication([coarse,precise])[0])==1


@pytest.mark.parametrize('changes',[
    {'identity_evidence':{}},
    {'identity_evidence':{'application_urls':['https://forms.gle/different-cohort']}},
    {'title':TITLE.replace('1기','2기')},
    {'application_start_at':None},
    {'application_end_at':None},
    {'application_end_at':'2026-11-12T15:00:00+09:00'},
    {'application_end_at':'2026-11-11T15:00:00'},
])
def test_near_titles_shared_form_or_partial_period_do_not_merge_distinct_opportunities(changes):
    left=row('left','portal-a')
    right=row('right','portal-b',application_start_at='2026-10-21T15:00:00+09:00',
              application_start_precision='DATETIME',application_end_at='2026-11-11T15:00:00+09:00',
              application_end_precision='DATETIME')
    right['snapshot'].update(changes)
    kept,dropped=deduplicate_publication([left,right])
    assert len(kept)==2 and not dropped


def test_same_board_different_publisher_ids_and_conflicting_precise_deadlines_stay_separate():
    a=row('a','portal-a',application_end_precision='DATETIME')
    b=row('b','portal-a',application_end_precision='DATETIME')
    assert len(deduplicate_publication([a,b])[0])==2
    b=row('b','portal-b',application_end_at='2026-11-11T15:00:00+09:00',application_end_precision='DATETIME')
    assert len(deduplicate_publication([a,b])[0])==2


def test_coarse_bridge_does_not_join_two_conflicting_precise_editions():
    a=row('a','portal-a',application_end_at='2026-11-11T15:00:00+09:00',application_end_precision='DATETIME')
    b=row('b','portal-b',application_end_at='2026-11-11T16:00:00+09:00',application_end_precision='DATETIME')
    coarse=row('coarse','portal-c')
    kept,dropped=deduplicate_publication([coarse,a,b])
    assert len(kept)==3 and not dropped


def test_identity_evidence_uses_structured_routes_without_signed_downloads_or_credentials():
    evidence=publication_identity_evidence({
        'aply_mthd_onli_rcpt_istc':ROUTE+'?utm_source=portal',
        'biz_gdnc_url':'publisher.example/board/view?id=91',
        'biz_aply_url':'https://user:password@publisher.example/apply',
        'official_application_links':['https://publisher.example/download?id=1',
                                      'https://publisher.example/form?id=1&downloadToken=secret',
                                      'https://publisher.example/',
                                      'javascript:alert(1)']})
    assert evidence=={'application_urls':[ROUTE],'publisher_urls':['https://publisher.example/board/view?id=91']}
    assert 'secret' not in str(evidence) and 'password' not in str(evidence)


def test_snapshot_projects_corroboration_without_creating_material_updates():
    program=Program(title=TITLE,organization='기관',official_url='https://portal.example/notice?id=1')
    before=snapshot(program,{})
    after=snapshot(program,{'aply_mthd_onli_rcpt_istc':ROUTE})
    assert after['identity_evidence']=={'application_urls':[ROUTE]}
    assert publication_fingerprint(before)==publication_fingerprint(after)
