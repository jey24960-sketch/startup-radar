"""Strict domain schemas. None means UNKNOWN, never false."""
from datetime import date, datetime
from enum import StrEnum
import math
from typing import Any, Literal
import re
from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator
from radar.support_types import SupportType, normalize


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class TeamStatus(StrEnum):
    PRE_TEAM='PRE_TEAM'; FORMING='FORMING'; TEAMED='TEAMED'
class ProductStage(StrEnum):
    IDEA='IDEA'; LANDING='LANDING'; MVP='MVP'; REVENUE='REVENUE'
class BusinessStatus(StrEnum):
    PRE_BUSINESS='PRE_BUSINESS'; SOLE_PROPRIETOR='SOLE_PROPRIETOR'; CORPORATION='CORPORATION'
class EligibilityStatus(StrEnum):
    ELIGIBLE='ELIGIBLE'; NEEDS_INFO='NEEDS_INFO'; INELIGIBLE='INELIGIBLE'; UNVERIFIABLE='UNVERIFIABLE'


class TeamProfile(StrictModel):
    team_status: TeamStatus | None = None
    product_stage: ProductStage | None = None
    business_status: BusinessStatus | None = None
    business_status_options: list[BusinessStatus] | None = None
    team_size: int | None = Field(default=None, ge=1, le=10000)
    founder_age: int | None = Field(default=None, ge=0, le=120)
    age_band: tuple[int,int] | None = None
    student_status: bool | None = None
    university_affiliation: str | None = None
    region: str | None = None
    business_registration_date: date | None = None
    business_age_months: int | None = Field(default=None, ge=0)
    industry: list[str] | None = None
    has_revenue: bool | None = None
    revenue: float | None = Field(default=None, ge=0)
    revenue_band: str | None = None
    investment_received: bool | None = None
    investment_stage: str | None = None
    preferred_program_types: list[SupportType] | None = None
    global_expansion_interest: bool | None = None
    applicant_type: str | None = None
    prior_support_restrictions: list[str] | None = None
    preset: int | None = Field(default=None, ge=0, le=4)
    assumed_fields: set[str] = Field(default_factory=set)

    @field_serializer('assumed_fields', when_used='json')
    def stable_assumed_fields(self, value):
        # Hash-randomized set iteration must not invalidate persisted profiles or
        # cache keys when a new batch process reads the same preset.
        return sorted(value)

    @model_validator(mode='after')
    def validate_ranges(self):
        if self.age_band and not 0 <= self.age_band[0] <= self.age_band[1] <= 120:
            raise ValueError('Invalid age band')
        if self.business_status and self.business_status_options and self.business_status not in self.business_status_options:
            raise ValueError('Business status contradicts options')
        return self


PRESETS = [
    ('팀빌딩 전 · 아이디어',dict(team_status='PRE_TEAM',product_stage='IDEA',business_status='PRE_BUSINESS',has_revenue=False)),
    ('팀 구성 · 아이디어',dict(team_status='TEAMED',product_stage='IDEA',business_status='PRE_BUSINESS')),
    ('랜딩 · 프리토타입',dict(team_status='TEAMED',product_stage='LANDING',business_status='PRE_BUSINESS')),
    ('MVP',dict(team_status='TEAMED',product_stage='MVP')),
    ('사업자등록 · 법인 보유',dict(business_status_options=['SOLE_PROPRIETOR','CORPORATION'])),
]


def apply_preset(profile: TeamProfile, index: int) -> TeamProfile:
    if not 0 <= index < len(PRESETS): raise ValueError('Unknown preset')
    data=profile.model_dump()
    for key in profile.assumed_fields: data[key]=None
    assumed=set()
    for key,value in PRESETS[index][1].items():
        if data.get(key) is None:
            if key=='business_status_options' and data.get('business_status') is not None: continue
            data[key]=value; assumed.add(key)
    data.update(preset=index, assumed_fields=assumed)
    return TeamProfile.model_validate(data)


def update_profile(profile: TeamProfile, changes: dict) -> TeamProfile:
    allowed=set(TeamProfile.model_fields)-{'preset','assumed_fields','business_status_options'}
    if not set(changes)<=allowed: raise ValueError('Unsupported profile field')
    data=profile.model_dump(); data.update(changes)
    data['assumed_fields']=profile.assumed_fields-set(changes)
    if 'business_status' in changes:
        data['business_status_options']=None
        data['assumed_fields'].discard('business_status_options')
    return TeamProfile.model_validate(data)


class Evidence(StrictModel):
    source_id: str | None = None
    document_id: str | None = None
    location: str | None = None
    text: str = Field(min_length=1, max_length=10000)
    method: Literal['STRUCTURED_API','HTML','DOCUMENT','LLM','MANUAL']
    confidence: float = Field(ge=0, le=1)
    verified: bool = False


RequirementKey = Literal['team_status','business_status','business_age_months','founder_age','region',
    'student_status','university_affiliation','team_size','product_stage','revenue','has_revenue',
    'investment_received','industry','applicant_type','registration_date','prior_support_restrictions','program_response']


class Requirement(StrictModel):
    key: RequirementKey
    operator: Literal['EQ','NEQ','IN','NOT_IN','GTE','LTE','RANGE','EXISTS']
    value: Any = None
    mandatory: bool = True
    certain: bool = False
    evidence: list[Evidence] = Field(default_factory=list)
    response_id: str | None = None
    question: str | None = Field(default=None, max_length=500)

    @model_validator(mode='after')
    def valid_operator(self):
        if self.key=='program_response':
            if (not self.response_id or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}',self.response_id)
                or not self.question or not self.question.strip() or self.operator!='EQ' or type(self.value) is not bool):
                raise ValueError('Program questions require a stable response ID, question and boolean EQ')
            return self
        if self.response_id is not None or self.question is not None:
            raise ValueError('Response identity belongs only to program questions')
        if self.operator=='EXISTS':
            if self.value is not None and self.value is not True:raise ValueError('EXISTS means a value must be present')
            return self
        if self.operator in ('IN','NOT_IN','RANGE') and not isinstance(self.value,list):
            raise ValueError('Operator requires an array')
        if self.value is None:raise ValueError('Missing requirement value')
        if self.key in ('industry','prior_support_restrictions') and self.operator not in ('IN','NOT_IN'):
            raise ValueError('Set-valued profile fields require IN/NOT_IN/EXISTS')
        values=self.value if isinstance(self.value,list) else [self.value]
        if not values:raise ValueError('Requirement values cannot be empty')
        numeric={'founder_age','business_age_months','team_size','revenue'}
        boolean={'student_status','has_revenue','investment_received'}
        enums={'team_status':TeamStatus,'product_stage':ProductStage,'business_status':BusinessStatus}
        if self.key in numeric:
            if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 for v in values):raise ValueError('Numeric requirement must use finite nonnegative numbers')
            if self.key!='revenue' and any(not isinstance(v,int) for v in values):raise ValueError('Age/month/team requirements must use integers')
        elif self.key in boolean:
            if self.operator not in ('EQ','NEQ') or type(self.value) is not bool:raise ValueError('Boolean requirement must use EQ/NEQ and true/false')
        else:
            if any(not isinstance(v,str) or not v.strip() for v in values):raise ValueError('Text requirement must use nonempty strings')
            if self.key in enums:
                if any(v not in [x.value for x in enums[self.key]] for v in values):raise ValueError('Invalid profile enum requirement')
            if self.key=='registration_date':
                for value in values:date.fromisoformat(value)
            elif self.operator in ('GTE','LTE','RANGE'):raise ValueError('Ordered comparison is only valid for numeric/date requirements')
        if self.operator=='RANGE' and (len(values)!=2 or values[0]>values[1]):raise ValueError('Invalid range')
        if self.operator in ('EQ','NEQ','GTE','LTE') and isinstance(self.value,list):raise ValueError('Scalar comparison requires a scalar value')
        return self


class EligibilityResult(StrictModel):
    status: EligibilityStatus
    as_of: date | None = None
    matched_requirements: list[Requirement] = Field(default_factory=list)
    failed_requirements: list[Requirement] = Field(default_factory=list)
    missing_profile_fields: list[str] = Field(default_factory=list)
    missing_program_questions: list[Requirement] = Field(default_factory=list)
    unverifiable_requirements: list[dict] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    engine_version: str = 'eligibility-2.1.0'


class Program(StrictModel):
    title: str = Field(min_length=1)
    organization: str = Field(min_length=1)
    program_types: list[str] = Field(default_factory=lambda: ['UNKNOWN'])
    official_url: str
    application_url: str | None = None
    application_start_at: datetime | None = None
    application_end_at: datetime | None = None
    application_start_precision: Literal['UNKNOWN','DATE','DATETIME']='UNKNOWN'
    application_end_precision: Literal['UNKNOWN','DATE','DATETIME']='UNKNOWN'
    deadline_type: Literal['FIXED_DATE','ROLLING','UNTIL_BUDGET_EXHAUSTED','UNKNOWN']='UNKNOWN'
    applicant_summary: str | None = None
    support_summary: str | None = None
    benefit_summary: str | None = None
    amount_min: float | None = None
    amount_max: float | None = None
    currency: str='KRW'
    requirements: list[Requirement] = Field(default_factory=list)
    evidence_complete: bool=False
    product_stages: list[ProductStage] = Field(default_factory=list)
    industry_tags: list[str] = Field(default_factory=list)
    global_relevance: bool=False
    document_hashes: list[str] = Field(default_factory=list)
    document_coverage: list[dict] = Field(default_factory=list)
    material_notes: list[str] = Field(default_factory=list)

    @field_validator('program_types')
    @classmethod
    def canonical_support_types(cls, values):
        return normalize(values)

    @model_validator(mode='after')
    def aware_dates(self):
        question_ids=[r.response_id for r in self.requirements if r.key=='program_response']
        if len(question_ids)!=len(set(question_ids)):
            raise ValueError('Program question IDs must be unique')
        for value in (self.application_start_at,self.application_end_at):
            if value and value.tzinfo is None: raise ValueError('Program dates must include timezone')
        if self.application_start_at and self.application_end_at and self.application_start_at>self.application_end_at:
            raise ValueError('Start follows end')
        return self
