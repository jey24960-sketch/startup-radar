"""Read-only V1/V2 comparison. A comparison never authorizes production cutover."""
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from radar.identity import normalize_text,normalize_url,duplicate_confidence
from radar.models import TeamProfile,Program
from radar.eligibility import evaluate
from radar.dates import program_status
from radar.recommendations import rank,configured_weights
from core.clock import now,SEOUL


def v2_snapshot(db,team_id,at=None):
    at=at or now()
    if at.tzinfo is None:raise ValueError('An aware comparison timestamp is required')
    at=at.astimezone(SEOUL);weights=configured_weights(db)
    with db.transaction() as c:
        profile=c.execute('select v.* from radar.team_profile_versions v join radar.team_profiles p on p.team_id=v.team_id and p.version=v.version where v.team_id=%s',(team_id,)).fetchone()
        if not profile:raise ValueError('Team profile not found')
        rows=c.execute('select v.* from radar.program_versions v join radar.programs p on p.current_version_id=v.id').fetchall()
        aliases=c.execute('select program_id,discovery_url,official_detail_url from radar.program_sources').fetchall()
        sources=c.execute('select s.slug,s.enabled,r.status,r.failures,r.created_at from radar.sources s '
            'left join lateral(select * from radar.source_run_results r where r.source_id=s.id order by r.created_at desc limit 1) r on true order by s.slug').fetchall()
        latest_run=c.execute('select id,started_at from radar.ingestion_runs order by started_at desc limit 1').fetchone()
    team=TeamProfile.model_validate(profile['profile']);programs=[]
    for row in rows:
        p=Program.model_validate(row['normalized']);outcome=evaluate(team,p.requirements,p.evidence_complete,at.date());ranking=rank(p,team,outcome,weights,at)
        programs.append({'id':str(row['program_id']),'version_id':str(row['id']),'title':p.title,'organization':p.organization,
            'official_url':p.official_url,'application_url':p.application_url,'status':program_status(p,at),
            'eligibility':outcome.model_dump(mode='json'),'recommendation':asdict(ranking) if ranking else None,
            'aliases':[url for a in aliases if a['program_id']==row['program_id'] for url in (a['discovery_url'],a['official_detail_url']) if url]})
    return {'observed_at':latest_run['started_at'].isoformat() if latest_run else None,'evaluated_at':at.isoformat(),
            'ingestion_run_id':str(latest_run['id']) if latest_run else None,'team_id':str(team_id),'profile_version_id':str(profile['id']),
            'profile':profile['profile'],'programs':programs,'source_results':sources}


def urls(item):
    return {normalize_url(u) for u in [item.get('official_url'),item.get('application_url'),item.get('apply_url'),*item.get('aliases',[])] if u}


def title_key(item):return normalize_text(item.get('title','')),normalize_text(item.get('organization',''))


def duplicate_groups(items):
    groups=defaultdict(list)
    for index,item in enumerate(items):groups[title_key(item)].append(index)
    return [indices for key,indices in groups.items() if key[0] and len(indices)>1]


def compare(v1,v2,max_time_gap_hours=6):
    if isinstance(v1,list):v1={'programs':v1,'status':'UNKNOWN'}
    if not isinstance(v1,dict) or not isinstance(v2,dict):raise ValueError('Expected report objects')
    left=v1.get('all_programs',v1.get('programs'));right=v2.get('programs')
    if not isinstance(left,list) or not isinstance(right,list):raise ValueError('Reports must contain program arrays')
    if any(not isinstance(i,dict) or not i.get('title') for i in left+right):raise ValueError('Invalid program record')
    matched=[];ambiguous=[];left_only=[];used=set()
    for index,item in enumerate(left):
        available=[(i,p) for i,p in enumerate(right) if i not in used]
        exact=[(i,p) for i,p in available if urls(item)&urls(p)]
        method='URL'
        if not exact:
            exact=[(i,p) for i,p in available if title_key(item)==title_key(p) and all(title_key(item))];method='TITLE_ORGANIZATION'
        if len(exact)==1:
            j,target=exact[0];used.add(j)
            state=target.get('eligibility',{}).get('status','UNVERIFIABLE')
            matched.append({'v1_index':index,'v2_index':j,'title':item['title'],'method':method,'program_id':target.get('id'),
                'v1_relevance_score':item.get('relevance_score'),'v2_eligibility':state,
                'v2_recommended':target.get('recommendation') is not None,
                'review_required':state in ('INELIGIBLE','UNVERIFIABLE') or target.get('recommendation') is None,
                'review_reason':'V1 inclusion/relevance is not a formal eligibility decision; inspect V2 evidence and filters' if state!='ELIGIBLE' else None})
        elif len(exact)>1:ambiguous.append({'v1_index':index,'candidate_v2_indices':[i for i,_ in exact],'reason':'Multiple exact candidates; no forced match'})
        else:
            candidates=[]
            for j,target in available:
                score=duplicate_confidence({'title':item['title'],'organization':item.get('organization',''),'official_url':item.get('apply_url') or 'https://invalid.example/v1/'+str(index)},
                                           {'title':target['title'],'organization':target.get('organization',''),'official_url':target.get('official_url') or 'https://invalid.example/v2/'+str(j)})
                if score>=0.8:candidates.append({'v2_index':j,'confidence':score})
            left_only.append({'index':index,'program':item,'possible_matches':candidates})
    limitations=[]
    if 'all_programs' not in v1:limitations.append('V1 report may contain only not-previously-sent items; discovery comparison is incomplete')
    if v1.get('status') not in ('SUCCESS','PARTIAL_SUCCESS','FAILED'):limitations.append('V1 analysis status is not recorded')
    timestamps=[]
    for report in (v1,v2):
        try:
            value=datetime.fromisoformat(report['observed_at'])
            if value.tzinfo is None:raise ValueError()
            timestamps.append(value)
        except (KeyError,ValueError,TypeError):limitations.append('A report has no trustworthy timezone-aware collection timestamp')
    if len(timestamps)==2 and abs((timestamps[0]-timestamps[1]).total_seconds())>max_time_gap_hours*3600:
        limitations.append('Collection periods differ by more than the configured comparison window')
    return {'schema_version':'parallel-2.0.0','generated_at':now().isoformat(),'cutover_approved':False,
        'counts':{'v1':len(left),'v2':len(right),'matched':len(matched),'v1_only':len(left_only),'v2_only':len(right)-len(used),'ambiguous':len(ambiguous)},
        'matched':matched,'v1_only':left_only,'v2_only':[{'index':i,'program':p} for i,p in enumerate(right) if i not in used],
        'ambiguous_matches':ambiguous,'duplicate_candidates':{'v1':duplicate_groups(left),'v2':duplicate_groups(right)},
        'failed_source_review':{'v1':v1.get('failed_sources'),'v1_analysis_failures':v1.get('analysis_failures'),
            'v2':[s for s in v2.get('source_results',[]) if s.get('enabled') and s.get('status')!='SUCCESS']},
        'context':{'v1_observed_at':v1.get('observed_at'),'v2_observed_at':v2.get('observed_at'),
                   'team_id':v2.get('team_id'),'profile_version_id':v2.get('profile_version_id')},
        'limitations':limitations+['V2 snapshot includes its stored catalog, including closed notices; compare statuses and individual source timestamps before interpreting V2-only counts',
            'No nationwide coverage percentage is computed','Human investigation and multi-run operating evidence are required before cutover']}
