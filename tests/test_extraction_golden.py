import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from radar.extraction import RequirementExtractor
from radar.adapters.base import AcquiredDetail,SourceFailure
from radar.models import Program,TeamProfile
from radar.eligibility import evaluate

CORPUS=json.loads((Path(__file__).parent/'fixtures'/'extraction_golden.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('case',CORPUS['cases'],ids=lambda case:case['id'])
def test_real_source_semantic_guard(case):
    requirements=[]
    if case.get('rule'):
        requirements=[{**case['rule'],'certain':True,'mandatory':True,'evidence':[
            {'source_id':'official','text':case['quote'],'method':'LLM','confidence':1}]}]
    payload={'requirements':requirements,'program_types':['EDUCATION'],
        'eligibility_section_quote':case['text'],'evidence_complete':bool(case.get('expected_review')),
        'date_evidence_quote':case.get('date_quote'),'application_end_at':case.get('end_at'),
        'deadline_type':case.get('deadline_type','FIXED_DATE' if case.get('end_at') else 'UNKNOWN')}
    client=SimpleNamespace(messages=SimpleNamespace(create=lambda **kwargs:SimpleNamespace(
        content=[SimpleNamespace(type='text',text=json.dumps(payload))])))
    extractor=RequirementExtractor(client);program=Program(title=case['id'],organization='Official fixture',official_url=case['url'])
    detail=AcquiredDetail(case['url'],case['text'],case['id'])
    if case.get('expected_error'):
        with pytest.raises(SourceFailure,match=case['expected_error']):extractor.extract(program,detail,[],'official')
        return
    result=extractor.extract(program,detail,[],'official')
    if case.get('expected_review'):
        assert case['expected_review'] in {flag['kind'] for flag in extractor.review_flags}
        assert not result.evidence_complete
        assert evaluate(TeamProfile(),result.requirements,result.evidence_complete).status=='UNVERIFIABLE'
    if case.get('expected_end_at'):assert result.application_end_at.isoformat()==case['expected_end_at']
    if case.get('expected_deadline_type'):assert result.deadline_type==case['expected_deadline_type'] and not result.evidence_complete


def test_corpus_covers_required_real_source_cases_and_keeps_scans_review_only():
    tags={tag for case in CORPUS['cases']+CORPUS['scanned_originals'] for tag in case['tags']}
    assert {'fixed_deadline','time_specific_deadline','rolling_deadline','founder_age','business_age','region',
        'student_requirement','product_stage','business_status','compound_and','compound_or',
        'future_attendance_commitment','prior_support_restriction','scanned_document','conflicting_body_attachment'}<=tags
    assert sum(case['pages'] for case in CORPUS['scanned_originals'])==15
