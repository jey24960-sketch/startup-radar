from copy import deepcopy
from radar.parallel import compare


def reports():
    a={'title':'창업 지원','organization':'기관','apply_url':'https://example.org/notice?utm_source=one','relevance_score':80}
    b={'id':'fixture-program','title':'창업 지원','organization':'기관','official_url':'https://example.org/notice','eligibility':{'status':'NEEDS_INFO'},'recommendation':{'score':70}}
    return {'status':'SUCCESS','observed_at':'2026-09-12T10:00:00+09:00','all_programs':[a],'failed_sources':[]}, {'observed_at':'2026-09-12T11:00:00+09:00','programs':[b],'source_results':[]}


def test_exact_alias_match_keeps_eligibility_separate_from_v1_score():
    a,b=reports();result=compare(a,b)
    assert result['counts']['matched']==1 and result['matched'][0]['method']=='URL'
    assert result['matched'][0]['v2_eligibility']=='NEEDS_INFO'
    assert result['matched'][0]['v1_relevance_score']==80 and result['cutover_approved'] is False


def test_changed_url_exact_title_org_and_rejected_eligibility_review():
    a,b=reports();b['programs'][0]['official_url']='https://example.org/changed';b['programs'][0]['eligibility']['status']='INELIGIBLE';b['programs'][0]['recommendation']=None
    result=compare(a,b)
    assert result['matched'][0]['method']=='TITLE_ORGANIZATION' and result['matched'][0]['review_required']


def test_ambiguous_exact_matches_never_force_merge():
    a,b=reports();b['programs'].append(deepcopy(b['programs'][0]))
    result=compare(a,b)
    assert result['counts']['matched']==0 and result['counts']['ambiguous']==1
    assert result['duplicate_candidates']['v2']==[[0,1]]


def test_failed_sources_and_mismatched_period_cannot_look_like_validation():
    a,b=reports();a['failed_sources']=['V1 source'];b['source_results']=[{'slug':'api','enabled':True,'status':'FAILED'}]
    b['observed_at']='2026-09-14T11:00:00+09:00';result=compare(a,b)
    assert result['failed_source_review']['v1']==['V1 source'] and result['failed_source_review']['v2'][0]['slug']=='api'
    assert any('periods differ' in text for text in result['limitations'])


def test_legacy_report_without_run_metadata_is_incomplete():
    a,b=reports();result=compare(a['all_programs'],b)
    assert any('not-previously-sent' in text for text in result['limitations'])
    assert any('timestamp' in text for text in result['limitations'])


def test_unique_items_are_retained_for_investigation():
    a,b=reports();b['programs'][0].update(title='다른 교육',organization='별도 기관',official_url='https://example.org/other')
    result=compare(a,b)
    assert result['counts']['v1_only']==1 and result['counts']['v2_only']==1
    assert result['v1_only'][0]['program']['title']=='창업 지원'


def test_latest_run_cannot_hide_stale_or_missing_source_intervals():
    a,b=reports()
    a.update(collection_started_at='2026-09-12T10:00:00+09:00',collection_completed_at='2026-09-12T10:05:00+09:00')
    b['source_results']=[
        dict(slug='fresh',enabled=True,status='SUCCESS',started_at='2026-09-12T10:01:00+09:00',finished_at='2026-09-12T10:03:00+09:00'),
        dict(slug='nearby',enabled=True,status='PARTIAL',started_at='2026-09-12T09:00:00+09:00',finished_at='2026-09-12T09:05:00+09:00'),
        dict(slug='stale',enabled=True,status='SUCCESS',started_at='2026-09-10T10:00:00+09:00',finished_at='2026-09-10T10:05:00+09:00'),
        dict(slug='unfinished',enabled=True,status='RUNNING',started_at='2026-09-12T10:00:00+09:00'),
    ]
    review=compare(a,b)['collection_review']
    assert [s['temporal_relation'] for s in review['v2_sources']]==['OVERLAPPING','NEARBY','OUTSIDE_WINDOW','MISSING_INTERVAL']
    assert not review['all_enabled_sources_within_window'] and not review['scope_equivalence_verified']


def test_same_korean_deadline_date_does_not_verify_time():
    a,b=reports();a['all_programs'][0]['deadline']='2026-09-30'
    b['programs'][0].update(application_end_at='2026-09-29T23:00:00+00:00',application_end_precision='DATETIME',deadline_type='FIXED_DATE')
    review=compare(a,b)['matched'][0]['deadline_review']
    assert review['result']=='SAME_DATE' and not review['time_verified_by_v1']
    b['programs'][0]['application_end_at']='2026-10-01T17:00:00+09:00'
    assert compare(a,b)['matched'][0]['deadline_review']['result']=='DATE_DIFFERS'
    b['programs'][0]['application_end_precision']='UNKNOWN'
    assert compare(a,b)['matched'][0]['deadline_review']['result']=='NOT_COMPARABLE'


def test_nearby_sources_and_complete_analysis_do_not_claim_equal_coverage():
    a,b=reports()
    a.update(collection_started_at='2026-09-12T10:00:00+09:00',collection_completed_at='2026-09-12T10:05:00+09:00')
    b['source_results']=[dict(slug='sample',enabled=True,status='PARTIAL',started_at='2026-09-12T09:00:00+09:00',finished_at='2026-09-12T09:05:00+09:00')]
    result=compare(a,b)
    assert result['collection_review']['all_enabled_sources_within_window']
    assert result['collection_review']['scope_equivalence_verified'] is False
    assert any('relevance threshold' in s for s in result['limitations'])
    assert result['cutover_approved'] is False


def test_homepage_or_shared_listing_url_never_establishes_program_identity():
    a,b=reports()
    for url in ('https://example.org/','https://example.org/list'):
        a['all_programs']=[dict(title='One',organization='A',apply_url=url),dict(title='Two',organization='B',apply_url=url)]
        b['programs']=[dict(title='Unrelated',organization='C',official_url=url)]
        assert compare(a,b)['counts']['matched']==0


def test_exact_title_with_different_organizer_is_a_review_candidate_only():
    a,b=reports();a['all_programs'][0].update(organization='기관 / 운영사',apply_url='https://example.org/')
    result=compare(a,b)
    assert result['counts']['matched']==0
    assert result['v1_only'][0]['possible_matches'][0]['v2_index']==0
