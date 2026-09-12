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
