"""Evidence-gated deterministic eligibility. No LLM decision enters this engine."""
from datetime import date
from radar.models import EligibilityResult, EligibilityStatus, TeamProfile, Requirement
from core.clock import today

REGION_ALIASES={
    'seoul':'서울','서울특별시':'서울','서울시':'서울',
    'busan':'부산','부산광역시':'부산','부산시':'부산',
    'gyeonggi':'경기','gyeonggi-do':'경기','경기도':'경기',
    'incheon':'인천','인천광역시':'인천','인천시':'인천',
    'daejeon':'대전','대전광역시':'대전','daegu':'대구','대구광역시':'대구',
    'gwangju':'광주','광주광역시':'광주','ulsan':'울산','울산광역시':'울산',
    'sejong':'세종','세종특별자치시':'세종','jeju':'제주','제주특별자치도':'제주',
    'gangwon':'강원','강원도':'강원','강원특별자치도':'강원',
    '충청북도':'충북','충청남도':'충남','전라북도':'전북','전북특별자치도':'전북',
    '전라남도':'전남','경상북도':'경북','경상남도':'경남'}


def region_value(value):
    if isinstance(value,list):return [region_value(v) for v in value]
    if isinstance(value,str):return REGION_ALIASES.get(value.strip().casefold(),value.strip())
    return value


def compare(actual, operator, value):
    if operator=='EQ': return actual==value
    if operator=='NEQ': return actual!=value
    if operator=='IN': return actual in value
    if operator=='NOT_IN': return actual not in value
    if operator=='GTE': return actual>=value
    if operator=='LTE': return actual<=value
    if operator=='RANGE': return value[0]<=actual<=value[1]
    if operator=='EXISTS': return actual is not None
    raise ValueError('Unsupported operator')


def evaluate(profile: TeamProfile, requirements: list[Requirement], evidence_complete: bool,
             as_of: date | None=None) -> EligibilityResult:
    as_of=as_of or today()
    result=EligibilityResult(status=EligibilityStatus.ELIGIBLE,as_of=as_of)
    if not evidence_complete:
        result.unverifiable_requirements.append({'reason':'Critical notice evidence is incomplete'})
    for rule in requirements:
        if not rule.mandatory: continue
        result.evidence.extend(rule.evidence)
        supported=rule.certain and any(e.verified and e.confidence>=0.8 and (e.source_id or e.document_id) for e in rule.evidence)
        if not supported:
            result.unverifiable_requirements.append({'requirement':rule.model_dump(mode='json'),'reason':'Unconfirmed source evidence'})
            continue
        key='business_registration_date' if rule.key=='registration_date' else rule.key
        actual=getattr(profile,key)
        if rule.key=='business_age_months' and profile.business_registration_date:
            start=profile.business_registration_date
            if start>as_of:
                actual=None
            else:
                actual=(as_of.year-start.year)*12+as_of.month-start.month-(as_of.day<start.day)
        alternatives=None
        if actual is None and rule.key=='founder_age' and profile.age_band:
            alternatives=range(profile.age_band[0],profile.age_band[1]+1)
        if actual is None and rule.key=='business_status' and profile.business_status_options:
            alternatives=profile.business_status_options
        if actual is None and alternatives is None:
            result.missing_profile_fields.append(rule.key); continue
        try:
            expected=rule.value
            if rule.key=='region':actual=region_value(actual);expected=region_value(expected)
            if isinstance(actual,date):
                expected=[date.fromisoformat(v) for v in expected] if isinstance(expected,list) else date.fromisoformat(expected)
            if alternatives is not None:
                outcomes=[compare(v,rule.operator,expected) for v in alternatives]
                if not outcomes or (any(outcomes) and not all(outcomes)):
                    result.missing_profile_fields.append(rule.key); continue
                matched=all(outcomes)
            elif isinstance(actual,list) and rule.operator in ('IN','NOT_IN'):
                matches=[v in expected for v in actual]
                matched=any(matches) if rule.operator=='IN' else not any(matches)
            else:
                matched=compare(actual,rule.operator,expected)
        except (TypeError,ValueError):
            result.unverifiable_requirements.append({'requirement':rule.model_dump(mode='json'),'reason':'Incompatible requirement values'})
            continue
        (result.matched_requirements if matched else result.failed_requirements).append(rule)
    result.missing_profile_fields=sorted(set(result.missing_profile_fields))
    if result.failed_requirements: result.status=EligibilityStatus.INELIGIBLE
    elif result.unverifiable_requirements: result.status=EligibilityStatus.UNVERIFIABLE
    elif result.missing_profile_fields: result.status=EligibilityStatus.NEEDS_INFO
    return result
