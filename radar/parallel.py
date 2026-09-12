"""Read-only V1/V2 comparison. A comparison never authorizes production cutover."""
from collections import Counter,defaultdict
from urllib.parse import urlsplit
from dataclasses import asdict
from datetime import date,datetime
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
        profile=c.execute('select v.* from startup_radar.team_profile_versions v join startup_radar.team_profiles p on p.team_id=v.team_id and p.version=v.version where v.team_id=%s',(team_id,)).fetchone()
        if not profile:raise ValueError('Team profile not found')
        rows=c.execute('select v.* from startup_radar.program_versions v join startup_radar.programs p on p.current_version_id=v.id').fetchall()
        aliases=c.execute('select a.program_id,a.discovery_url,a.official_detail_url,a.last_seen_at,s.slug from startup_radar.program_sources a join startup_radar.sources s on s.id=a.source_id').fetchall()
        sources=c.execute('select s.slug,s.name,s.enabled,r.status,r.failures,r.created_at,r.run_id,r.discovered_count,r.fetched_count,r.parsed_count,i.started_at,i.finished_at from startup_radar.sources s '
            'left join lateral(select * from startup_radar.source_run_results r where r.source_id=s.id order by r.created_at desc limit 1) r on true '
            'left join startup_radar.ingestion_runs i on i.id=r.run_id order by s.slug').fetchall()
        latest_run=c.execute('select id,started_at from startup_radar.ingestion_runs order by started_at desc limit 1').fetchone()
    for source in sources:
        source['failures']=[{'kind':f.get('kind')} for f in source.get('failures') or []]
    team=TeamProfile.model_validate(profile['profile']);programs=[]
    for row in rows:
        p=Program.model_validate(row['normalized']);outcome=evaluate(team,p.requirements,p.evidence_complete,at.date());ranking=rank(p,team,outcome,weights,at)
        programs.append({'id':str(row['program_id']),'version_id':str(row['id']),'title':p.title,'organization':p.organization,
            'official_url':p.official_url,'application_url':p.application_url,'status':program_status(p,at),
            'application_start_at':p.application_start_at.isoformat() if p.application_start_at else None,
            'application_end_at':p.application_end_at.isoformat() if p.application_end_at else None,
            'application_start_precision':p.application_start_precision,'application_end_precision':p.application_end_precision,
            'deadline_type':p.deadline_type,
            'source_observations':[{'slug':a['slug'],'last_seen_at':a['last_seen_at'].isoformat()} for a in aliases if a['program_id']==row['program_id']],
            'eligibility':outcome.model_dump(mode='json'),'recommendation':asdict(ranking) if ranking else None,
            'aliases':[url for a in aliases if a['program_id']==row['program_id'] for url in (a['discovery_url'],a['official_detail_url']) if url]})
    return {'observed_at':latest_run['started_at'].isoformat() if latest_run else None,'evaluated_at':at.isoformat(),
            'ingestion_run_id':str(latest_run['id']) if latest_run else None,'team_id':str(team_id),'profile_version_id':str(profile['id']),
            'profile':profile['profile'],'programs':programs,'source_results':sources,'scope':'STORED_CATALOG',
            'timestamp_semantics':'observed_at is the latest ingestion start, not a collection timestamp for every catalog item'}


def aware_time(value):
    try:
        value=value if isinstance(value,datetime) else datetime.fromisoformat(value)
        return value if value.tzinfo is not None else None
    except (TypeError,ValueError):return None


def deadline_review(left,right):
    end=aware_time(right.get('application_end_at'))
    try:old=date.fromisoformat(left.get('deadline'))
    except (TypeError,ValueError):old=None
    comparable=old is not None and end is not None and right.get('application_end_precision') in ('DATE','DATETIME') and right.get('deadline_type')=='FIXED_DATE'
    return {'v1_date':left.get('deadline'),'v2_end_at':right.get('application_end_at'),
            'v2_precision':right.get('application_end_precision'),'v2_deadline_type':right.get('deadline_type'),
            'result':('SAME_DATE' if old==end.astimezone(SEOUL).date() else 'DATE_DIFFERS') if comparable else 'NOT_COMPARABLE',
            'time_verified_by_v1':False}


def collection_review(v1,v2,max_time_gap_hours):
    start=aware_time(v1.get('collection_started_at'));end=aware_time(v1.get('collection_completed_at'))
    if start and end and end<start:start=end=None
    results=[]
    for source in v2.get('source_results',[]):
        if not source.get('enabled'):continue
        s=aware_time(source.get('started_at'));e=aware_time(source.get('finished_at'))
        state='MISSING_INTERVAL';gap=None
        if start and end and s and e and s<=e:
            gap=max(0,(s-end).total_seconds(),(start-e).total_seconds())/3600
            state='OVERLAPPING' if gap==0 else 'NEARBY' if gap<=max_time_gap_hours else 'OUTSIDE_WINDOW'
        results.append({'slug':source.get('slug'),'name':source.get('name'),'run_id':str(source['run_id']) if source.get('run_id') else None,
            'status':source.get('status'),'started_at':s.isoformat() if s else None,'finished_at':e.isoformat() if e else None,
            'temporal_relation':state,'gap_hours':gap,'discovered_count':source.get('discovered_count'),
            'parsed_count':source.get('parsed_count')})
    all_nearby=bool(results) and all(s['temporal_relation'] in ('OVERLAPPING','NEARBY') for s in results)
    return {'max_gap_hours':max_time_gap_hours,'v1_started_at':start.isoformat() if start else None,
            'v1_completed_at':end.isoformat() if end else None,'v2_sources':results,
            'all_enabled_sources_within_window':all_nearby,'scope_equivalence_verified':False}


def urls(item):
    return {normalize_url(u) for u in [item.get('official_url'),item.get('application_url'),item.get('apply_url'),*item.get('aliases',[])]
            if u and (urlsplit(u).path.strip('/') or urlsplit(u).query)}


def title_key(item):return normalize_text(item.get('title','')),normalize_text(item.get('organization',''))


def duplicate_groups(items):
    groups=defaultdict(list)
    for index,item in enumerate(items):groups[title_key(item)].append(index)
    return [indices for key,indices in groups.items() if key[0] and len(indices)>1]


def compare(v1,v2,max_time_gap_hours=6):
    if max_time_gap_hours<0:raise ValueError('Comparison window must be nonnegative')
    if isinstance(v1,list):v1={'programs':v1,'status':'UNKNOWN'}
    if not isinstance(v1,dict) or not isinstance(v2,dict):raise ValueError('Expected report objects')
    left=v1.get('all_programs',v1.get('programs'));right=v2.get('programs')
    if not isinstance(left,list) or not isinstance(right,list):raise ValueError('Reports must contain program arrays')
    if any(not isinstance(i,dict) or not i.get('title') for i in left+right):raise ValueError('Invalid program record')
    left_urls=Counter(u for item in left for u in urls(item));right_urls=Counter(u for item in right for u in urls(item))
    identifying_urls={u for u,count in left_urls.items() if count==1 and right_urls[u]==1}
    matched=[];ambiguous=[];left_only=[];used=set()
    for index,item in enumerate(left):
        available=[(i,p) for i,p in enumerate(right) if i not in used]
        exact=[(i,p) for i,p in available if urls(item)&urls(p)&identifying_urls]
        method='URL'
        if not exact:
            exact=[(i,p) for i,p in available if title_key(item)==title_key(p) and all(title_key(item))];method='TITLE_ORGANIZATION'
        if len(exact)==1:
            j,target=exact[0];used.add(j)
            state=target.get('eligibility',{}).get('status','UNVERIFIABLE')
            matched.append({'v1_index':index,'v2_index':j,'title':item['title'],'method':method,'program_id':target.get('id'),
                'deadline_review':deadline_review(item,target),
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
                same_title=title_key(item)[0]==title_key(target)[0]
                if score>=0.8 or same_title:
                    candidates.append({'v2_index':j,'confidence':score,
                        'reason':'Same normalized title; organization or URL differs' if same_title else 'Similar identity requires review',
                        'deadline_review':deadline_review(item,target)})
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
    collection=collection_review(v1,v2,max_time_gap_hours)
    if not collection['all_enabled_sources_within_window']:
        limitations.append('Not every enabled V2 source has a completed collection interval within the V1 comparison window')
    return {'schema_version':'parallel-2.0.1','generated_at':now().isoformat(),'cutover_approved':False,
        'collection_review':collection,
        'counts':{'v1':len(left),'v2':len(right),'matched':len(matched),'v1_only':len(left_only),'v2_only':len(right)-len(used),'ambiguous':len(ambiguous)},
        'matched':matched,'v1_only':left_only,'v2_only':[{'index':i,'program':p} for i,p in enumerate(right) if i not in used],
        'ambiguous_matches':ambiguous,'duplicate_candidates':{'v1':duplicate_groups(left),'v2':duplicate_groups(right)},
        'failed_source_review':{'v1':v1.get('failed_sources'),'v1_analysis_failures':v1.get('analysis_failures'),
            'v2':[s for s in v2.get('source_results',[]) if s.get('enabled') and s.get('status')!='SUCCESS']},
        'context':{'v1_observed_at':v1.get('observed_at'),'v2_observed_at':v2.get('observed_at'),
                   'v1_profile':v1.get('profile'),'v2_profile':v2.get('profile'),
                   'v1_minimum_relevance_score':v1.get('minimum_relevance_score'),'v1_configured_sources':v1.get('configured_sources'),
                   'team_id':v2.get('team_id'),'profile_version_id':v2.get('profile_version_id')},
        'limitations':limitations+['V2 snapshot includes its stored catalog, including closed notices; compare statuses and individual source timestamps before interpreting V2-only counts',
            'V1 all_programs still excludes model omissions, expired items and items below its relevance threshold',
            'Nearby collection times do not establish identical source scopes or equivalent team profiles',
            'No nationwide coverage percentage is computed','Human investigation and multi-run operating evidence are required before cutover']}
