"""Synthetic Korean evidence cases; these do not measure a live model's accuracy."""
import json
from datetime import date,timedelta
from types import SimpleNamespace
import pytest
from radar.adapters.base import AcquiredDetail,SourceFailure
from radar.extraction import RequirementExtractor,cited_datetime
from radar.models import Program,TeamProfile,Requirement,Evidence
from radar.eligibility import evaluate
from radar.dates import program_status,korean_date


def extract(result,text,program=None):
    program=program or Program(title='Fixture 모집',organization='Fixture 기관',official_url='https://example.org/fixture')
    payload={'requirements':[],'program_types':['EDUCATION'],'eligibility_section_quote':text,'evidence_complete':True,**result}
    client=SimpleNamespace(messages=SimpleNamespace(create=lambda **kwargs:SimpleNamespace(content=[SimpleNamespace(type='text',text=json.dumps(payload))])))
    return RequirementExtractor(client).extract(program,AcquiredDetail(program.official_url,text,program.title),[],'source')


def age_rule(quote):
    return {'key':'founder_age','operator':'LTE','value':39,'certain':True,
        'evidence':[{'source_id':'source','text':quote,'method':'LLM','confidence':1,'verified':True}]}


def test_unsupported_or_cannot_become_a_confirmed_hard_failure():
    text='만 39세 이하 또는 학생이면 신청할 수 있습니다.'
    program=extract({'requirements':[age_rule(text)],'unsupported_logic':True},text)
    outcome=evaluate(TeamProfile(founder_age=45,student_status=True),program.requirements,program.evidence_complete)
    assert outcome.status=='UNVERIFIABLE' and not outcome.failed_requirements


def test_independent_structured_rule_survives_unreliable_ai_output():
    rule=Requirement(key='business_status',operator='EQ',value='PRE_BUSINESS',certain=True,
        evidence=[Evidence(source_id='official-api',text='예비창업자 대상',method='STRUCTURED_API',confidence=1,verified=True)])
    original=Program(title='Fixture',organization='Org',official_url='https://example.org/1',requirements=[rule])
    program=extract({'unsupported_logic':True},'복잡한 추가 조건',original)
    assert evaluate(TeamProfile(business_status='CORPORATION'),program.requirements,program.evidence_complete).status=='INELIGIBLE'
    assert original.model_dump()==Program(title='Fixture',organization='Org',official_url='https://example.org/1',requirements=[rule]).model_dump()


def test_whitespace_citation_is_not_supporting_evidence():
    program=extract({'requirements':[age_rule('   ')]},'연령 제한 없음')
    assert evaluate(TeamProfile(founder_age=50),program.requirements,program.evidence_complete).status=='UNVERIFIABLE'


@pytest.mark.parametrize('quote,value,hour',[
    ('접수 마감: 2026. 9. 30.(수) 오전 11시까지','2026-09-30T11:00:00+09:00',11),
    ('접수 마감: 2026년 9월 30일 오후 1시 30분','2026-09-30T13:30:00+09:00',13),
    ('2026-09-30 18:00 마감','2026-09-30T18:00:00+09:00',18),
    ('2026.09.30 오후 12시','2026-09-30T12:00:00+09:00',12),
    ('2026.09.30 오전 12시','2026-09-30T00:00:00+09:00',0)])
def test_cited_cutoff_preserves_seoul_time(quote,value,hour):
    parsed=cited_datetime(value,quote,True)
    assert parsed.hour==hour and parsed.utcoffset()==timedelta(hours=9)


def test_notice_closes_immediately_after_cited_11am_cutoff():
    text='신청 마감 2026.9.30.(수) 오전 11시까지. 누구나 신청 가능합니다.'
    program=extract({'application_end_at':'2026-09-30T11:00:00+09:00','date_evidence_quote':'2026.9.30.(수) 오전 11시까지','deadline_type':'FIXED_DATE'},text)
    assert program_status(program,program.application_end_at)=='OPEN'
    assert program_status(program,program.application_end_at+timedelta(seconds=1))=='CLOSED'


def test_date_only_citation_cannot_hide_source_cutoff_time():
    with pytest.raises(SourceFailure,match='AI_DATE_TIME_REQUIRED'):
        extract({'application_end_date':'2026-09-30','date_evidence_quote':'2026.9.30'},'2026.9.30, 접수 종료 시각은 오전 11시입니다.')


@pytest.mark.parametrize('value,quote,kind',[
    ('2026-09-30','2026.9.30 오전 11시','AI_DATE_TIME_REQUIRED'),
    ('2026-09-30T23:59:00+09:00','2026.9.30 오전 11시','AI_DATE_EVIDENCE'),
    ('2027-09-30','2026.9.30 마감','AI_DATE_EVIDENCE'),
    ('2026-09-30T11:00:00','2026.9.30 오전 11시','AI_DATE_SCHEMA'),
    ('2026-09-30','9/30까지','AI_DATE_EVIDENCE')])
def test_inaccurate_or_unquoted_temporal_fact_is_rejected(value,quote,kind):
    with pytest.raises(SourceFailure,match=kind):cited_datetime(value,quote,True)


def test_date_only_retains_documented_end_of_day_convention():
    assert cited_datetime('2026-09-30','2026년 9월 30일까지',True)==korean_date('20260930',True)


def test_failed_extraction_does_not_partially_mutate_official_program():
    original=Program(title='Fixture',organization='Org',official_url='https://example.org/1')
    before=original.model_dump()
    with pytest.raises(SourceFailure):
        extract({'application_start_date':'2026-09-01','application_end_date':'2027-09-30',
            'date_evidence_quote':'2026.9.1부터 2026.9.30까지'},'2026.9.1부터 2026.9.30까지',original)
    assert original.model_dump()==before


def test_unsupported_benefit_is_not_promoted_to_fact():
    assert extract({'benefit_summary':'1억원 지급'},'무료 창업 교육').benefit_summary is None
    assert extract({'benefit_summary':'무료 교육','benefit_evidence_quote':'무료 창업 교육'},'무료 창업 교육').benefit_summary=='무료 교육'


def test_existing_structured_deadline_is_not_replaced_by_ai():
    original=Program(title='Fixture',organization='Org',official_url='https://example.org/1',application_end_at=korean_date('20260920',True))
    result=extract({'application_end_date':'2026-09-30','date_evidence_quote':'2026.9.30까지'},'2026.9.30까지',original)
    assert result.application_end_at==original.application_end_at


def test_known_registration_date_satisfies_exists():
    rule=Requirement(key='registration_date',operator='EXISTS',certain=True,evidence=[Evidence(source_id='source',text='사업자등록 필요',method='MANUAL',confidence=1,verified=True)])
    assert evaluate(TeamProfile(business_registration_date=date(2026,1,1)),[rule],True).status=='ELIGIBLE'
