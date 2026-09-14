"""One storage/provenance path for APIs, official channels and verified referrals."""
from psycopg.types.json import Jsonb
from radar.opportunity_facts import classify,strict_duplicate_key,EXCLUDED_TITLE
from radar.identity import digest


def attach_api_facts(program, detail, source):
    # A public aggregator can also list a private organizer; do not infer its type.
    facts=classify(program.title,detail.text,{'organization_type':'UNKNOWN','official_url':program.official_url})
    facts.recruitment_confirmed=not bool(EXCLUDED_TITLE.search(program.title))
    facts.review_reasons=[r for r in facts.review_reasons if r!='RECRUITMENT_UNCONFIRMED']
    if facts.category=='OTHER':facts.category='PUBLIC_SUPPORT'
    if facts.participation=='UNKNOWN':facts.participation='TEAM_RECRUITMENT';facts.review_reasons.remove('PARTICIPATION_UNKNOWN')
    facts.application_link_verified=bool(program.application_url)
    facts.evidence['official_api']={'url':program.official_url,'source':source['slug'],'fields':'Official API structured fields; detailed eligibility unverified'}
    if not program.application_end_at and program.deadline_type=='UNKNOWN':facts.review_reasons.append('DEADLINE_UNKNOWN')
    if not program.applicant_summary:facts.review_reasons.append('APPLICANT_UNKNOWN')
    program.opportunity=facts.model_dump()


def record_opportunity(db,program,saved,source,detail):
    from radar.weekly import snapshot
    f=program.opportunity
    if not f:return
    facts={**snapshot(program,detail.raw_metadata),**f,'program_types':program.program_types}
    facts['evidence']={**f.get('evidence',{}),'official_source':{'url':program.official_url,'source':source['slug']}}
    with db.transaction() as c:
        prior=c.execute('select * from startup_radar.opportunity_records where program_id=%s for update',(saved['program_id'],)).fetchone()
        from radar.weekly import MATERIAL
        observation=digest({key:facts.get(key) for key in MATERIAL})
        observations=dict(prior['facts'].get('source_observations',{})) if prior else {}
        alternate=bool(prior and prior['facts'].get('primary_source') not in (None,source['slug']))
        reasons=list(f.get('review_reasons',[]))
        if not program.applicant_summary and 'APPLICANT_UNKNOWN' not in reasons:reasons.append('APPLICANT_UNKNOWN')
        conflict=bool(prior and prior['editorial_conflict'])
        if alternate:
            # Cross-posts add provenance, not alternating canonical text every day.
            changed=source['slug'] in observations and observations[source['slug']]!=observation
            disagreement=any(facts.get(k)!=prior['facts'].get(k) for k in ('application_end_at','cancelled','fee','investment_terms'))
            facts=dict(prior['facts']);reasons=list(prior['review_reasons'])
            if changed or disagreement:reasons.append('ALTERNATE_SOURCE_CHANGED')
            saved={**saved,'version_id':prior['base_version_id']}
            f={**f,'recruitment_confirmed':prior['confirmed']}
        facts['primary_source']=facts.get('primary_source',source['slug'])
        observations[source['slug']]=observation
        facts['source_observations']=observations
        if prior and prior['editorial']:
            conflict|=any(prior['facts'].get(key)!=facts.get(key) for key in prior['editorial'])
        if conflict:reasons.append('EDITORIAL_CONFLICT')
        ambiguous=c.execute('select candidate_program_id from startup_radar.possible_duplicates where program_id=%s',(saved['program_id'],)).fetchall()
        if ambiguous:reasons.append('POSSIBLE_DUPLICATE')
        facts['possible_duplicates']=[str(r['candidate_program_id']) for r in ambiguous]
        origins=c.execute('select official_detail_url,source_program_id,s.name,s.slug from startup_radar.program_sources p join startup_radar.sources s on s.id=p.source_id where program_id=%s or program_id in (select program_id from startup_radar.opportunity_records where duplicate_of=%s)',(saved['program_id'],saved['program_id'])).fetchall()
        facts['sources']=[dict(r) for r in origins]
        material_changed=not prior or any(prior['facts'].get(k)!=facts.get(k) for k in MATERIAL)
        c.execute('insert into startup_radar.opportunity_records(program_id,base_version_id,facts,confirmed,review_reasons,duplicate_key) '
            'values(%s,%s,%s,%s,%s,%s) on conflict(program_id) do update set '
            'base_version_id=excluded.base_version_id,facts=excluded.facts,confirmed=excluded.confirmed,review_reasons=excluded.review_reasons,'
            'duplicate_key=excluded.duplicate_key,editorial_conflict=%s,last_verified_at=now(),'
            'last_changed_at=case when %s then now() else opportunity_records.last_changed_at end,'
            'revision=opportunity_records.revision+case when opportunity_records.base_version_id<>excluded.base_version_id or opportunity_records.facts<>excluded.facts then 1 else 0 end',
            (saved['program_id'],saved['version_id'],Jsonb(facts),f['recruitment_confirmed'],list(dict.fromkeys(reasons)),strict_duplicate_key(program),conflict,material_changed))


def catalog_collection(db):
    """Publication consumes stored daily observations; it never recollects sources."""
    with db.transaction() as c:
        latest=c.execute("select * from startup_radar.ingestion_runs where trigger_type='daily-discovery' and status<>'RUNNING' order by started_at desc limit 1").fetchone()
        if not latest:return {'id':None,'status':'FAILED','sources':[],'weekly_programs':[]}
        # Do not present a week-old feed as a fresh empty scan.
        if not c.execute("select %s::timestamptz>now()-interval '36 hours' fresh",(latest['finished_at'],)).fetchone()['fresh']:
            return {'id':str(latest['id']),'status':'FAILED','sources':[],'weekly_programs':[]}
        rows=c.execute("select o.program_id,o.base_version_id version_id,o.facts||o.editorial snapshot,startup_radar.opportunity_status(o.facts||o.editorial) status "
            "from startup_radar.opportunity_records o where o.confirmed and o.included and o.duplicate_of is null and not o.editorial_conflict "
            "and (not ('PAST_NOTICE_DEADLINE_UNKNOWN'=any(o.review_reasons)) or nullif(o.editorial->>'application_end_at','') is not null) "
            "and o.last_verified_at>now()-interval '8 days'").fetchall()
    return {'id':str(latest['id']),'status':latest['status'],'sources':latest['summary'].get('sources',[]),'weekly_programs':[dict(r) for r in rows]}
