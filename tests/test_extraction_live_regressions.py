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
