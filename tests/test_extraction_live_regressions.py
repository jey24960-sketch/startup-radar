import json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from radar.extraction import RequirementExtractor
from radar.models import Program
from radar.adapters.base import AcquiredDetail
from radar.eligibility import evaluate
from radar.models import TeamProfile


def extract(rule,quote):
    rule={**rule,'certain':True,'mandatory':True,'evidence':[
        {'source_id':'official','text':quote,'method':'LLM','confidence':1}]}
    response={'requirements':[rule],'program_types':['GRANT'],
              'eligibility_section_quote':quote,'evidence_complete':True}
    client=SimpleNamespace(messages=SimpleNamespace(create=Mock(return_value=SimpleNamespace(
        content=[SimpleNamespace(type='text',text=json.dumps(response))]))))
    p=Program(title='Notice',organization='Official',official_url='https://example.org/notice')
    return RequirementExtractor(client).extract(p,AcquiredDetail(p.official_url,quote,p.title),[],'official')


def test_designation_cannot_be_certified_by_arbitrary_profile_presence():
    p=extract({'key':'prior_support_restrictions','operator':'EXISTS','value':None},
              '지원대상 : 2026년 현재 착한가격업소 지정 사업장')
    profile=TeamProfile(prior_support_restrictions=['unrelated value'])
    assert not p.evidence_complete and not p.requirements[0].certain
    assert evaluate(profile,p.requirements,p.evidence_complete).status=='UNVERIFIABLE'


def test_region_not_named_in_quoted_eligibility_cannot_create_hard_failure():
    p=extract({'key':'region','operator':'IN','value':['인천광역시 부평구']},
              '지원대상 : 2026년 현재 착한가격업소 지정 사업장')
    assert p.requirements[0].evidence[0].verified
    assert not p.requirements[0].certain and not p.evidence_complete
    assert evaluate(TeamProfile(region='서울'),p.requirements,p.evidence_complete).status=='UNVERIFIABLE'


def test_explicit_region_quote_still_supports_deterministic_rejection():
    p=extract({'key':'region','operator':'EQ','value':'인천광역시 부평구'},
              '지원대상: 인천광역시 부평구 소재 사업장')
    assert p.requirements[0].certain and p.evidence_complete
    assert evaluate(TeamProfile(region='서울'),p.requirements,p.evidence_complete).status=='INELIGIBLE'


def test_free_text_history_cannot_certify_absence_of_tax_credit_or_industry_exclusions():
    p=extract({'key':'prior_support_restrictions','operator':'NOT_IN','value':['국세 또는 지방세 체납 사업자']},
              '제외대상: 국세 또는 지방세 체납 사업자')
    assert not p.evidence_complete and not p.requirements[0].certain
    assert evaluate(TeamProfile(prior_support_restrictions=[]),p.requirements,p.evidence_complete).status=='UNVERIFIABLE'


@pytest.mark.parametrize('quote',[
    '예비창업자 또는 창업 7년 이내 창업기업',
    '창업 7년 이내 창업기업 (공고일 기준)',
])
def test_branch_or_fixed_reference_age_cannot_become_a_current_date_global_limit(quote):
    p=extract({'key':'business_age_months','operator':'LTE','value':84},quote)
    for profile in (TeamProfile(business_status='PRE_BUSINESS'),TeamProfile(business_age_months=100)):
        result=evaluate(profile,p.requirements,p.evidence_complete)
        assert result.status=='UNVERIFIABLE' and not result.failed_requirements


def test_future_registration_promise_not_proven_by_present_business_status():
    p=extract({'key':'business_status','operator':'EQ','value':'PRE_BUSINESS'},
              '예비창업자: 입주 후 3개월 이내 사업자등록이 가능한 자')
    assert not p.evidence_complete
    assert evaluate(TeamProfile(business_status='PRE_BUSINESS'),p.requirements,p.evidence_complete).status=='UNVERIFIABLE'


def test_independent_age_limit_remains_usable():
    p=extract({'key':'business_age_months','operator':'LTE','value':84},'신청일 현재 창업 7년 이내 사업자만 신청 가능')
    assert p.evidence_complete and p.requirements[0].certain
    assert evaluate(TeamProfile(business_age_months=100),p.requirements,p.evidence_complete).status=='INELIGIBLE'


def test_broad_applicant_category_cannot_exclude_prebusiness_applicants():
    p=extract({'key':'business_status','operator':'IN','value':['SOLE_PROPRIETOR','CORPORATION']},'대상: 일반기업, 1인 창조기업')
    assert evaluate(TeamProfile(business_status='PRE_BUSINESS'),p.requirements,p.evidence_complete).status=='UNVERIFIABLE'
    assert not p.requirements[0].certain


def test_explicit_registered_business_condition_still_supports_rejection():
    p=extract({'key':'business_status','operator':'IN','value':['SOLE_PROPRIETOR','CORPORATION']},'신청일 현재 사업자등록을 완료한 기업만 지원 가능')
    assert evaluate(TeamProfile(business_status='PRE_BUSINESS'),p.requirements,p.evidence_complete).status=='INELIGIBLE'


def test_procurement_facility_alternative_cannot_be_reduced_to_generic_region():
    quote='신청대상\n수도권에 본사 또는 공장이 소재한 공공조달시장 관심 기업'
    p=extract({'key':'region','operator':'IN','value':['수도권']},quote)
    assert not p.evidence_complete and not p.requirements[0].certain
    for region in (None,'서울','부산'):
        # Neither approval nor rejection follows from a generic team location:
        # its headquarters/factory may be elsewhere.
        result=evaluate(TeamProfile(business_status='PRE_BUSINESS',region=region),p.requirements,p.evidence_complete)
        assert result.status=='UNVERIFIABLE' and not result.failed_requirements


def test_omitted_enterprise_rule_detected_even_when_model_omits_all_rules():
    from radar.extraction_review import omitted_applicant_conditions
    text='수도권에 본사 또는 공장이 소재한 공공조달시장 관심 기업'
    flags=omitted_applicant_conditions({'official':text},[],text,'')
    assert {f['kind'] for f in flags}=={'BUSINESS_STATUS_NOT_EXPLICIT','FACILITY_LOCATION_NOT_REPRESENTED'}
    assert all(f['quotes']==[text] for f in flags)
    assert omitted_applicant_conditions({'official':'다른 원문'},[],text,text)==[]
    assert omitted_applicant_conditions({'official':text},[],'누구나 참여 가능','')==[]


def test_ordinary_region_and_independent_hard_failure_survive_review():
    from radar.models import Requirement,Evidence
    from radar.extraction_review import rule_review_reasons
    rule=Requirement(key='region',operator='EQ',value='서울',certain=True,
        evidence=[Evidence(source_id='official',text='서울 거주 예비창업자',method='LLM',confidence=1,verified=True)])
    assert rule_review_reasons(rule)==[]
    quote='수도권에 본사 또는 공장이 소재한 기업'
    p=extract({'key':'region','operator':'IN','value':['수도권']},quote)
    p.requirements.append(Requirement(key='founder_age',operator='LTE',value=39,certain=True,
        evidence=[Evidence(source_id='official',text='만 39세 이하',method='STRUCTURED_API',confidence=1,verified=True)]))
    assert evaluate(TeamProfile(founder_age=45),p.requirements,p.evidence_complete).status=='INELIGIBLE'
