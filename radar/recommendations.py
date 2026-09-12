"""Eligibility first; deterministic ranking second. Components remain inspectable."""
from dataclasses import dataclass,asdict
from psycopg.types.json import Jsonb
from radar.models import Program,TeamProfile
from radar.eligibility import evaluate
from radar.dates import program_status,days_left

EXCLUDED={'POLICY_LOAN','SME_FINANCING','GENERIC_RD'}
DEFAULT_WEIGHTS={'stage':25,'profile':20,'preference':15,'benefit':10,'global':10,'runway':10,'completeness':10}

def configured_weights(db):
    with db.transaction() as c:
        row=c.execute("select value from startup_radar.runtime_settings where key='recommendation_weights'").fetchone()
    return row['value'] if row else DEFAULT_WEIGHTS


@dataclass
class Ranking:
    score: float
    components: dict
    explanation: str
    provider: str='deterministic'
    model: str | None=None
    prompt_version: str='ranking-2.0.0'
    schema_version: str='recommendation-2.0.0'


def rank(program,profile,eligibility,weights=None,at=None):
    if eligibility.status not in ('ELIGIBLE','NEEDS_INFO'):return None
    if program_status(program,at) not in ('OPEN','UPCOMING'):return None
    if EXCLUDED.intersection(program.program_types):return None
    if not program.program_types or set(program.program_types)=={'UNKNOWN'}:return None
    weights=weights or DEFAULT_WEIGHTS
    if set(weights)!=set(DEFAULT_WEIGHTS) or any(v<0 for v in weights.values()) or sum(weights.values())<=0:
        raise ValueError('Invalid recommendation weights')
    remaining=days_left(program,at)
    known=len(eligibility.matched_requirements)
    values={
      'stage':1 if profile.product_stage and profile.product_stage in program.product_stages else 0.5 if not program.product_stages else 0,
      'profile':known/max(1,known+len(eligibility.missing_profile_fields)) if eligibility.missing_profile_fields else 1,
      'preference':1 if set(profile.preferred_program_types or []).intersection(program.program_types) else 0.5 if not profile.preferred_program_types else 0,
      'benefit':1 if program.benefit_summary or program.amount_max else 0,
      'global':1 if profile.global_expansion_interest and ('GLOBAL' in program.program_types or program.global_relevance) else 0.5 if profile.global_expansion_interest is None else 0,
      'runway':0.5 if remaining is None else 1 if remaining>=7 else max(0,remaining)/7,
      'completeness':1 if program.evidence_complete else 0,
    }
    components={key:{'value':value,'weight':weights[key],'points':round(value*weights[key],2)} for key,value in values.items()}
    score=round(sum(v['points'] for v in components.values())/sum(weights.values())*100,2)
    reasons=[]
    if values['stage']==1:reasons.append('제품 단계와 일치')
    if values['preference']==1:reasons.append('선호 지원 유형')
    if remaining is not None:reasons.append(f'마감까지 {remaining}일')
    if eligibility.status=='NEEDS_INFO':reasons.append('추가 정보 필요: '+', '.join(eligibility.missing_profile_fields))
    return Ranking(score,components,' · '.join(reasons) or '확인된 지원 조건과 자료 완전성을 기준으로 추천')


def refresh_recommendations(db,team_id=None):
    results=[]
    weights=configured_weights(db)
    with db.transaction() as c:
        profiles=c.execute('select v.* from startup_radar.team_profile_versions v join startup_radar.team_profiles p on p.team_id=v.team_id and p.version=v.version '
                           'where (%s::uuid is null or v.team_id=%s)',(team_id,team_id)).fetchall()
        programs=c.execute('select v.* from startup_radar.program_versions v join startup_radar.programs p on p.current_version_id=v.id').fetchall()
        for profile_row in profiles:
            profile=TeamProfile.model_validate(profile_row['profile'])
            for row in programs:
                program=Program.model_validate(row['normalized'])
                outcome=evaluate(profile,program.requirements,program.evidence_complete)
                ev=c.execute('insert into startup_radar.eligibility_evaluations(team_id,profile_version_id,program_version_id,status,result,engine_version) '
                    'values(%s,%s,%s,%s,%s,%s) returning id',(profile_row['team_id'],profile_row['id'],row['id'],outcome.status,
                    Jsonb(outcome.model_dump(mode='json')),outcome.engine_version)).fetchone()['id']
                ranking=rank(program,profile,outcome,weights=weights)
                if ranking:
                    c.execute('insert into startup_radar.recommendations(team_id,evaluation_id,score,components,provider,model,prompt_version,schema_version,explanation) '
                        'values(%s,%s,%s,%s,%s,%s,%s,%s,%s)',(profile_row['team_id'],ev,ranking.score,Jsonb(ranking.components),ranking.provider,
                         ranking.model,ranking.prompt_version,ranking.schema_version,ranking.explanation))
                results.append({'team_id':str(profile_row['team_id']),'program_version_id':str(row['id']),'status':outcome.status,'score':ranking.score if ranking else None})
    return results
