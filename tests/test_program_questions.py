import pytest
from radar.models import Requirement, Evidence, TeamProfile, Program
from radar.eligibility import evaluate


def question(**changes):
    values=dict(key='program_response',response_id='offline',question='Can your team attend the required session?',
                operator='EQ',value=True,certain=True,evidence=[Evidence(source_id='source',text='Attendance is required',
                method='MANUAL',verified=True,confidence=1)])
    return Requirement(**(values|changes))


@pytest.mark.parametrize('value,status',[(None,'NEEDS_INFO'),(True,'ELIGIBLE'),(False,'INELIGIBLE'),('true','NEEDS_INFO'),(1,'NEEDS_INFO')])
def test_program_declarations_are_explicit_booleans_not_profile_facts(value,status):
    profile=TeamProfile();result=evaluate(profile,[question()],True,program_responses={'offline':value})
    assert result.status==status and result.missing_profile_fields==[]
    assert len(result.missing_program_questions)==(status=='NEEDS_INFO')
    assert profile.model_dump()==TeamProfile().model_dump()


def test_question_answer_cannot_override_incomplete_or_uncertain_source():
    assert evaluate(TeamProfile(),[question()],False,program_responses={'offline':True}).status=='UNVERIFIABLE'
    assert evaluate(TeamProfile(),[question(certain=False)],True,program_responses={'offline':True}).status=='UNVERIFIABLE'
    failed=Requirement(key='business_status',operator='EQ',value='PRE_BUSINESS',certain=True,evidence=question().evidence)
    assert evaluate(TeamProfile(business_status='CORPORATION'),[failed,question()],False).status=='INELIGIBLE'


@pytest.mark.parametrize('changes',[{'response_id':None},{'question':''},{'value':'true'},{'operator':'NEQ'},
                                  {'response_id':'../different'},{'key':'student_status'}])
def test_question_schema_rejects_ambiguous_identity_or_values(changes):
    with pytest.raises(ValueError):question(**changes)


def test_question_ids_are_unique_per_version():
    with pytest.raises(ValueError):
        Program(title='Fixture',organization='Fixture',official_url='https://example.org',requirements=[question(),question()])
