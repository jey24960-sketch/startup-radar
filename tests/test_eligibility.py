from datetime import date,datetime,timedelta,timezone
import pytest
from pydantic import ValidationError
from radar.models import TeamProfile,Requirement,Evidence,Program,apply_preset,update_profile
from radar.eligibility import evaluate
from radar.dates import program_status,days_left,korean_date


def rule(key,op,value,**extra):
    return Requirement(key=key,operator=op,value=value,certain=True,
        evidence=[Evidence(source_id='official',text='Original notice eligibility',method='STRUCTURED_API',confidence=1,verified=True)],**extra)


def test_preset_zero_no_optional_information():
    p=apply_preset(TeamProfile(),0)
    assert p.team_status=='PRE_TEAM' and p.product_stage=='IDEA' and p.business_status=='PRE_BUSINESS'
    assert p.has_revenue is False and p.founder_age is None and p.region is None
    assert evaluate(p,[rule('business_status','EQ','PRE_BUSINESS')],True).status=='ELIGIBLE'


def test_presets_preserve_explicit_profile():
    p=apply_preset(TeamProfile(),0)
    p=update_profile(p,{'business_status':'CORPORATION','region':'Seoul'})
    p=apply_preset(p,2)
    assert p.business_status=='CORPORATION' and p.region=='Seoul' and p.product_stage=='LANDING'


def test_mvp_does_not_infer_registration():
    assert apply_preset(TeamProfile(),3).business_status is None


def test_registered_preset_independent_of_product():
    p=apply_preset(TeamProfile(product_stage='IDEA'),4)
    assert p.product_stage=='IDEA' and p.business_status is None
    assert evaluate(p,[rule('business_status','IN',['SOLE_PROPRIETOR','CORPORATION'])],True).status=='ELIGIBLE'
    assert evaluate(p,[rule('business_status','EQ','CORPORATION')],True).status=='NEEDS_INFO'


def test_unknown_age_and_region():
    result=evaluate(TeamProfile(business_status='PRE_BUSINESS'),[
        rule('founder_age','LTE',39),rule('region','EQ','Seoul'),rule('business_status','EQ','PRE_BUSINESS')],True)
    assert result.status=='NEEDS_INFO' and result.missing_profile_fields==['founder_age','region']


def test_hard_failure_overrides_missing_and_unverifiable():
    result=evaluate(TeamProfile(business_status='PRE_BUSINESS'),[
        rule('business_status','IN',['CORPORATION','SOLE_PROPRIETOR']),rule('founder_age','LTE',39)],False)
    assert result.status=='INELIGIBLE' and result.failed_requirements


def test_insufficient_evidence_is_not_eligible():
    assert evaluate(TeamProfile(),[],False).status=='UNVERIFIABLE'
    r=rule('founder_age','LTE',39);r.evidence[0].verified=False
    assert evaluate(TeamProfile(founder_age=20),[r],True).status=='UNVERIFIABLE'


@pytest.mark.parametrize('age,expected',[(19,'INELIGIBLE'),(20,'ELIGIBLE'),(39,'ELIGIBLE'),(40,'INELIGIBLE')])
def test_age_range(age,expected):
    assert evaluate(TeamProfile(founder_age=age),[rule('founder_age','RANGE',[20,39])],True).status==expected


@pytest.mark.parametrize('band,expected',[((20,29),'ELIGIBLE'),((40,49),'INELIGIBLE'),((35,44),'NEEDS_INFO')])
def test_age_band_is_conservative(band,expected):
    assert evaluate(TeamProfile(age_band=band),[rule('founder_age','LTE',39)],True).status==expected


def test_business_age_and_same_program_two_teams():
    requirement=rule('business_age_months','LTE',36)
    a=TeamProfile(business_registration_date=date(2024,1,15))
    b=TeamProfile(business_registration_date=date(2020,1,15))
    assert evaluate(a,[requirement],True,date(2026,1,14)).status=='ELIGIBLE'
    assert evaluate(b,[requirement],True,date(2026,1,14)).status=='INELIGIBLE'


def test_prebusiness_only_rejects_registered_company():
    assert evaluate(TeamProfile(business_status='CORPORATION'),[rule('business_status','EQ','PRE_BUSINESS')],True).status=='INELIGIBLE'


def test_region_and_multiple_conditions():
    p=TeamProfile(region='Seoul',student_status=True,team_size=3)
    assert evaluate(p,[rule('region','IN',['Seoul','Gyeonggi']),rule('student_status','EQ',True),rule('team_size','GTE',2)],True).status=='ELIGIBLE'


def test_privacy_rejects_unnecessary_fields():
    with pytest.raises(ValidationError): TeamProfile(home_address='precise private address')


def test_schema_failure():
    with pytest.raises(ValidationError): Requirement(key='founder_age',operator='RANGE',value=[40,20])


def test_dates_and_seoul_boundaries():
    p=Program(title='x',organization='x',official_url='https://example.org',deadline_type='FIXED_DATE',
              application_start_at=korean_date('20260901'),application_end_at=korean_date('20260912',end=True))
    assert program_status(p,korean_date('20260831'))=='UPCOMING'
    assert program_status(p,korean_date('20260912'))=='OPEN'
    assert program_status(p,datetime(2026,9,12,15,0,tzinfo=timezone.utc))=='CLOSED'
    assert days_left(p,korean_date('20260905'))==7
    assert days_left(p,korean_date('20260909'))==3
    p.application_start_at=None;p.application_end_at=None;p.deadline_type='ROLLING'
    assert program_status(p)=='OPEN' and days_left(p) is None
