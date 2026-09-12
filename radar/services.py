"""Application queries. Membership-authorized facts and private operations stay separate."""
from dataclasses import asdict
from uuid import UUID
from radar.models import TeamProfile,Program,apply_preset
from radar.eligibility import evaluate
from radar.dates import program_status,days_left
from radar.recommendations import rank,configured_weights


def require_admin(db,user_id):
    with db.transaction(user_id) as c:
        if c.execute('select public.my_role() as role').fetchone()['role']!='admin':
            raise PermissionError('Administrator access required')


def require_member(db,user_id):
    with db.transaction(user_id) as c:
        if c.execute('select public.my_role() as role').fetchone()['role'] not in ('member','admin'):
            raise PermissionError('Verified GFC membership required')


def memberships(db,user_id):
    with db.transaction(user_id) as c:
        teams=c.execute('select t.id,t.name,m.role,p.profile,p.version from startup_radar.teams t join startup_radar.team_members m on m.team_id=t.id '
            'join startup_radar.team_profiles p on p.team_id=t.id where m.user_id=%s order by t.created_at',(user_id,)).fetchall()
        admin=c.execute('select public.my_role() as role').fetchone()['role']=='admin'
    return {'user_id':str(user_id),'teams':teams,'is_admin':admin}


def profile_for(db,user_id,team_id=None,preset=None):
    require_member(db,user_id)
    own=memberships(db,user_id)
    if team_id:
        selected=next((t for t in own['teams'] if str(t['id'])==str(team_id)),None)
        if not selected:raise PermissionError('Team is not accessible')
        if preset is not None:raise ValueError('Choose a team or a preset, not both')
        return TeamProfile.model_validate(selected['profile'])
    if preset is not None:return apply_preset(TeamProfile(),preset)
    return apply_preset(TeamProfile(),0)


def public_program(row,profile,weights=None):
    program=Program.model_validate(row['normalized'])
    outcome=evaluate(profile,program.requirements,program.evidence_complete)
    ranking=rank(program,profile,outcome,weights=weights)
    return {'id':str(row['program_id']),'version_id':str(row['id']),'version':row['version'],
            'status':program_status(program),'days_left':days_left(program),'facts':program.model_dump(mode='json'),
            'eligibility':outcome.model_dump(mode='json'),'recommendation':asdict(ranking) if ranking else None,
            'updated_at':row['created_at']}


def browse(db,user_id,team_id=None,preset=None,q='',program_type=None,status=None,eligibility=None,history=False,recommended=False,limit=30,offset=0,date_from=None,date_to=None):
    profile=profile_for(db,user_id,team_id,preset)
    from radar.feed import cached_browse
    return cached_browse(db,user_id,profile,team_id,q,program_type,status,eligibility,history,recommended,limit,offset,date_from,date_to)


def detail(db,user_id,program_id,team_id=None,preset=None,version_id=None):
    profile=profile_for(db,user_id,team_id,preset)
    weights=configured_weights(db)
    with db.transaction(user_id) as c:
        row=c.execute('select v.* from startup_radar.program_versions v join startup_radar.programs p on p.id=v.program_id '
            'where p.id=%s and v.id=coalesce(%s::uuid,p.current_version_id)',(program_id,version_id)).fetchone()
        if not row:raise LookupError('Program/version not found')
        result=public_program(row,profile,weights)
        result['versions']=c.execute('select id,version,created_at from startup_radar.program_versions where program_id=%s order by version desc',(program_id,)).fetchall()
        result['documents']=c.execute('select id,original_url,filename,detected_mime,content_hash,fetch_status,extraction_status,error_kind,error_message,fetched_at '
                                      'from startup_radar.documents where program_version_id=%s',(row['id'],)).fetchall()
        result['changes']=c.execute('select event_type,changed_fields,created_at from startup_radar.program_change_events where program_id=%s order by created_at desc',(program_id,)).fetchall()
    return result


def health(db,user_id=None):
    if user_id is not None:require_admin(db,user_id)
    with db.transaction() as c:
        sources=c.execute("select s.id,s.slug,s.name,s.adapter,s.enabled,s.config->>'disabled_reason' as disabled_reason,s.config->>'last_audit_failure' as last_audit_failure,s.last_attempted_at,s.last_successful_at,r.status,r.discovered_count,r.fetched_count,r.parsed_count,r.failures,r.latency_ms "
            'from startup_radar.sources s left join lateral(select * from startup_radar.source_run_results r where r.source_id=s.id order by r.created_at desc limit 1) r on true order by s.slug').fetchall()
        runs=c.execute('select * from startup_radar.ingestion_runs order by started_at desc limit 20').fetchall()
        jobs=c.execute('select * from startup_radar.job_requests order by created_at desc limit 20').fetchall()
        claims=c.execute('select * from startup_radar.schedule_claims order by created_at desc limit 20').fetchall()
        settings=c.execute('select key,value,updated_at from startup_radar.runtime_settings order by key').fetchall()
        failure_counts=c.execute("select (select count(*) from startup_radar.documents where extraction_status in ('FAILED','UNSUPPORTED')) documents, "
            "(select count(*) from startup_radar.ingestion_runs where summary->>'eligibility_error' is not null) eligibility").fetchone()
    active=[s for s in sources if s['enabled']]
    success=sum(s['status']=='SUCCESS' for s in active)
    return {'sources':sources,'runs':runs,'jobs':jobs,'schedule_claims':claims,'settings':settings,'failure_counts':failure_counts,'tracked_sources':len(sources),
            'enabled_sources':len(active),'successful_sources':success,
            'tracked_source_success_rate':round(100*success/len(active),1) if active else None,
            'coverage_note':'등록된 활성 소스의 최근 수집 성공률이며 국내 전체 창업지원사업의 포괄률이 아닙니다.'}


def admin_trace(db,user_id,recommendation_id):
    require_admin(db,user_id)
    with db.transaction() as c:
        rec=c.execute('select * from startup_radar.recommendations where id=%s',(recommendation_id,)).fetchone()
        if not rec:raise LookupError('Recommendation not found')
        profile_for(db,user_id,rec['team_id'])
        ev=c.execute('select * from startup_radar.eligibility_evaluations where id=%s',(rec['evaluation_id'],)).fetchone()
        version=c.execute('select * from startup_radar.program_versions where id=%s',(ev['program_version_id'],)).fetchone()
        profile=c.execute('select * from startup_radar.team_profile_versions where id=%s',(ev['profile_version_id'],)).fetchone()
        sources=c.execute('select ps.*,s.name from startup_radar.program_sources ps join startup_radar.sources s on s.id=ps.source_id where ps.program_id=%s',(version['program_id'],)).fetchall()
        docs=c.execute('select * from startup_radar.documents where program_version_id=%s',(version['id'],)).fetchall()
        notifications=c.execute('select * from startup_radar.notification_items where recommendation_id=%s',(recommendation_id,)).fetchall()
        snapshots=c.execute('select o.*,s.name from startup_radar.program_source_snapshots o join startup_radar.sources s on s.id=o.source_id where o.program_version_id=%s order by o.observed_at',(version['id'],)).fetchall()
    return {'recommendation':rec,'evaluation':ev,'program_version':version,'profile_version':profile,'provenance':sources,'source_snapshots':snapshots,'documents':docs,'notifications':notifications}
