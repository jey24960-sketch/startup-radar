"""Evidence-gated deterministic eligibility. No LLM decision enters this engine."""
from datetime import date
from radar.models import EligibilityResult, EligibilityStatus, TeamProfile, Requirement
from core.clock import today


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
    result=EligibilityResult(status=EligibilityStatus.ELIGIBLE)
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
