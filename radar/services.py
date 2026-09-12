"""Application queries. Membership-authorized facts and private operations stay separate."""
from dataclasses import asdict
from uuid import UUID
from radar.models import TeamProfile,Program,apply_preset
from radar.eligibility import evaluate
from radar.dates import program_status,days_left
from radar.recommendations import rank,configured_weights


def require_admin(db,user_id):
    with db.transaction(user_id) as c:
        if not c.execute('select 1 from radar.admin_users where user_id=%s',(user_id,)).fetchone():
            raise PermissionError('Administrator access required')


def memberships(db,user_id):
    with db.transaction(user_id) as c:
        teams=c.execute('select t.id,t.name,m.role,p.profile,p.version from radar.teams t join radar.team_members m on m.team_id=t.id '
            'join radar.team_profiles p on p.team_id=t.id where m.user_id=%s order by t.created_at',(user_id,)).fetchall()
        admin=c.execute('select 1 from radar.admin_users where user_id=%s',(user_id,)).fetchone() is not None
    return {'user_id':str(user_id),'teams':teams,'is_admin':admin}


def profile_for(db,user_id,team_id=None,preset=None):
    own=memberships(db,user_id)
    if not own['teams'] and not own['is_admin']:raise PermissionError('GFC invitation or team membership required')
    if preset is not None:return apply_preset(TeamProfile(),preset)
    if team_id:
        selected=next((t for t in own['teams'] if str(t['id'])==str(team_id)),None)
        if not selected:raise PermissionError('Team is not accessible')
        return TeamProfile.model_validate(selected['profile'])
    return apply_preset(TeamProfile(),0)


def public_program(row,profile,weights=None):
    program=Program.model_validate(row['normalized'])
    outcome=evaluate(profile,program.requirements,program.evidence_complete)
    ranking=rank(program,profile,outcome,weights=weights)
    return {'id':str(row['program_id']),'version_id':str(row['id']),'version':row['version'],
            'status':program_status(program),'days_left':days_left(program),'facts':program.model_dump(mode='json'),
            'eligibility':outcome.model_dump(mode='json'),'recommendation':asdict(ranking) if ranking else None,
            'updated_at':row['created_at']}


def browse(db,user_id,team_id=None,preset=None,q='',program_type=None,status=None,eligibility=None,history=False,recommended=False,limit=30,offset=0):
    profile=profile_for(db,user_id,team_id,preset)
    weights=configured_weights(db)
    with db.transaction(user_id) as c:
        rows=c.execute('select v.* from radar.program_versions v join radar.programs p on p.current_version_id=v.id '
                       'where (%s=\'\' or p.title ilike %s or p.organization ilike %s) order by v.created_at desc',
                       (q,'%'+q+'%','%'+q+'%')).fetchall()
    output=[]
    for row in rows:
        item=public_program(row,profile,weights)
        if not history and item['status']=='CLOSED':continue
        if program_type and program_type not in item['facts']['program_types']:continue
        if status and item['status']!=status:continue
        if eligibility and item['eligibility']['status']!=eligibility:continue
        if recommended and item['recommendation'] is None:continue
        output.append(item)
    if recommended:output.sort(key=lambda i:i['recommendation']['score'],reverse=True)
    return {'items':output[offset:offset+limit],'total':len(output),'profile':profile.model_dump(mode='json'),'offset':offset,'limit':limit}


def detail(db,user_id,program_id,team_id=None,preset=None,version_id=None):
    profile=profile_for(db,user_id,team_id,preset)
    weights=configured_weights(db)
    with db.transaction(user_id) as c:
        row=c.execute('select v.* from radar.program_versions v join radar.programs p on p.id=v.program_id '
            'where p.id=%s and v.id=coalesce(%s::uuid,p.current_version_id)',(program_id,version_id)).fetchone()
        if not row:raise LookupError('Program/version not found')
        result=public_program(row,profile,weights)
        result['versions']=c.execute('select id,version,created_at from radar.program_versions where program_id=%s order by version desc',(program_id,)).fetchall()
        result['documents']=c.execute('select id,original_url,filename,detected_mime,content_hash,fetch_status,extraction_status,error_kind,error_message,fetched_at '
                                      'from radar.documents where program_version_id=%s',(row['id'],)).fetchall()
        result['changes']=c.execute('select event_type,changed_fields,created_at from radar.program_change_events where program_id=%s order by created_at desc',(program_id,)).fetchall()
    return result


def health(db,user_id=None):
    if user_id is not None:require_admin(db,user_id)
    with db.transaction() as c:
        sources=c.execute("select s.id,s.slug,s.name,s.adapter,s.enabled,s.config->>'disabled_reason' as disabled_reason,s.config->>'last_audit_failure' as last_audit_failure,s.last_attempted_at,s.last_successful_at,r.status,r.discovered_count,r.fetched_count,r.parsed_count,r.failures,r.latency_ms "
            'from radar.sources s left join lateral(select * from radar.source_run_results r where r.source_id=s.id order by r.created_at desc limit 1) r on true order by s.slug').fetchall()
        runs=c.execute('select * from radar.ingestion_runs order by started_at desc limit 20').fetchall()
        jobs=c.execute('select * from radar.job_requests order by created_at desc limit 20').fetchall()
        settings=c.execute('select key,value,updated_at from radar.runtime_settings order by key').fetchall()
    active=[s for s in sources if s['enabled']]
    success=sum(s['status']=='SUCCESS' for s in active)
    return {'sources':sources,'runs':runs,'jobs':jobs,'settings':settings,'tracked_sources':len(sources),
            'enabled_sources':len(active),'successful_sources':success,
            'tracked_source_success_rate':round(100*success/len(active),1) if active else None,
            'coverage_note':'등록된 활성 소스의 최근 수집 성공률이며 국내 전체 창업지원사업의 포괄률이 아닙니다.'}


def admin_trace(db,user_id,recommendation_id):
    require_admin(db,user_id)
    with db.transaction() as c:
        rec=c.execute('select * from radar.recommendations where id=%s',(recommendation_id,)).fetchone()
        if not rec:raise LookupError('Recommendation not found')
        ev=c.execute('select * from radar.eligibility_evaluations where id=%s',(rec['evaluation_id'],)).fetchone()
        version=c.execute('select * from radar.program_versions where id=%s',(ev['program_version_id'],)).fetchone()
        profile=c.execute('select * from radar.team_profile_versions where id=%s',(ev['profile_version_id'],)).fetchone()
        sources=c.execute('select ps.*,s.name from radar.program_sources ps join radar.sources s on s.id=ps.source_id where ps.program_id=%s',(version['program_id'],)).fetchall()
        docs=c.execute('select * from radar.documents where program_version_id=%s',(version['id'],)).fetchall()
        notifications=c.execute('select * from radar.notification_items where recommendation_id=%s',(recommendation_id,)).fetchall()
        snapshots=c.execute('select o.*,s.name from radar.program_source_snapshots o join radar.sources s on s.id=o.source_id where o.program_version_id=%s order by o.observed_at',(version['id'],)).fetchall()
    return {'recommendation':rec,'evaluation':ev,'program_version':version,'profile_version':profile,'provenance':sources,'source_snapshots':snapshots,'documents':docs,'notifications':notifications}
