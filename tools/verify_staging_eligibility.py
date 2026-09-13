"""Evaluate synthetic hosted-DB roundtrip profiles with the actual Python engine."""
import json
from pathlib import Path
from radar.models import TeamProfile, Program, Requirement, Evidence
from radar.eligibility import evaluate


def main():
    hosted=json.loads(Path('docs/HOSTED-RLS-VERIFICATION.json').read_text(encoding='utf-8'))
    assert hosted['status']=='PASS' and hosted['seed_rolled_back']
    program=Program.model_validate(hosted['program'])
    assert program.official_url.startswith('https://example.invalid/staging/')
    results=[]
    for row in hosted['scenarios']:
        profile=TeamProfile.model_validate(row['profile'])
        actual=evaluate(profile,program.requirements,program.evidence_complete)
        expected='ELIGIBLE' if profile.business_status=='CORPORATION' else 'INELIGIBLE'
        assert actual.status==expected
        results.append({'name':row['name'],'profile':profile.model_dump(mode='json'),
                        'eligibility':actual.model_dump(mode='json')})
    zero=TeamProfile.model_validate(next(r['profile'] for r in hosted['scenarios'] if r['profile']['preset']==0))
    age=Requirement(key='founder_age',operator='LTE',value=39,certain=True,
                    evidence=[Evidence(source_id='staging-fixture',text='Synthetic age limit 39',
                                       method='MANUAL',verified=True,confidence=1)])
    assert zero.founder_age is None and zero.region is None
    assert evaluate(zero,[],True).status=='ELIGIBLE'
    missing=evaluate(zero,[age],True)
    assert missing.status=='NEEDS_INFO' and missing.missing_profile_fields==['founder_age']
    assert evaluate(zero,[],False).status=='UNVERIFIABLE'
    report={'status':'PASS','fixture_only':True,'profiles_roundtripped_through_hosted_db':True,
            'python_engine':'eligibility-2.0.2','real_notice_or_model_accuracy_claim':False,
            'results':results,'stage_zero_no_optional_data':True,
            'unknown_age_result':missing.model_dump(mode='json'),
            'missing_evidence_result':'UNVERIFIABLE'}
    Path('docs/HOSTED-ELIGIBILITY-VERIFICATION.json').write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':'PASS','scenarios':len(results),
                      'results':[(r['name'],r['eligibility']['status']) for r in results]},ensure_ascii=True))


if __name__=='__main__':main()
