"""Operational evidence quality; never changes facts or eligibility decisions."""
from collections import Counter
from datetime import datetime,timedelta
from psycopg.types.json import Jsonb
from core.clock import now
from radar.models import Program
from radar.dates import program_status,days_left

VERSION='quality-1'
REASONS=frozenset({
    'MISSING_DEADLINE_EVIDENCE','MISSING_ELIGIBILITY_EVIDENCE','MISSING_APPLICATION_URL',
    'OCR_REQUIRED','DOCUMENT_PARSE_FAILED','DOCUMENT_TOO_LARGE','AI_SCHEMA_FAILED',
    'AI_DATE_EVIDENCE_FAILED','AI_DATE_PRECISION_FAILED','SOURCE_CONFLICT','SOURCE_UNAVAILABLE',
    'COMPLEX_OR_REQUIRES_REVIEW','FUTURE_COMMITMENT_REQUIRED','STALE_SOURCE',
    'UNKNOWN_TARGET_CONDITION','OTHER_REVIEW_REQUIRED',
})
ERROR_REASONS={
    'DOCUMENT_OCR_REQUIRED':'OCR_REQUIRED','DOCUMENT_OCR_REVIEW':'OCR_REQUIRED','DOCUMENT_OCR_SETUP':'OCR_REQUIRED',
    'DOCUMENT_LIMIT':'DOCUMENT_TOO_LARGE','SIZE_LIMIT':'DOCUMENT_TOO_LARGE','RESPONSE_TOO_LARGE':'DOCUMENT_TOO_LARGE',
    'DOCUMENT_PARSE':'DOCUMENT_PARSE_FAILED','DOCUMENT_PROCESS':'DOCUMENT_PARSE_FAILED',
    'DOCUMENT_TIMEOUT':'DOCUMENT_PARSE_FAILED','DOCUMENT_EMPTY':'DOCUMENT_PARSE_FAILED',
    'AI_SCHEMA':'AI_SCHEMA_FAILED','AI_NORMALIZATION':'AI_SCHEMA_FAILED','AI_TRUNCATED':'AI_SCHEMA_FAILED',
    'AI_DATE_SCHEMA':'AI_DATE_EVIDENCE_FAILED','AI_DATE_EVIDENCE':'AI_DATE_EVIDENCE_FAILED',
    'AI_DATE_TIME_REQUIRED':'AI_DATE_PRECISION_FAILED','AI_DATE_CONFLICT':'SOURCE_CONFLICT',
    'AI_DATE_EVENT_NOT_DEADLINE':'AI_DATE_EVIDENCE_FAILED',
    'SOURCE_REVIEW_CHANGED':'SOURCE_CONFLICT','DETAIL_UNAVAILABLE':'SOURCE_UNAVAILABLE',
    'FUTURE_COMMITMENT_NOT_REPRESENTED':'FUTURE_COMMITMENT_REQUIRED',
    'PROGRAM_QUESTION_REVIEW_REQUIRED':'FUTURE_COMMITMENT_REQUIRED',
    'UNCLASSIFIED_REVIEW':'COMPLEX_OR_REQUIRES_REVIEW',
    'STUDENT_ALTERNATIVES_NOT_REPRESENTED':'COMPLEX_OR_REQUIRES_REVIEW',
    'PREFERENCE_NOT_MANDATORY':'UNKNOWN_TARGET_CONDITION',
    'FORM_OPTION_NOT_REQUIREMENT':'UNKNOWN_TARGET_CONDITION',
}


def assess(program,documents,metadata,last_seen_at,at=None,raw_text=''):
    at=at or now();reasons=set();metadata=metadata or {}
    if isinstance(last_seen_at,str):last_seen_at=datetime.fromisoformat(last_seen_at)
    if not program.evidence_complete:reasons.add('MISSING_ELIGIBILITY_EVIDENCE')
    if program.deadline_type=='UNKNOWN' or program.deadline_type=='FIXED_DATE' and not program.application_end_at:
        reasons.add('MISSING_DEADLINE_EVIDENCE')
    if not program.application_url:reasons.add('MISSING_APPLICATION_URL')
    if not last_seen_at or at-last_seen_at>timedelta(hours=24):reasons.add('STALE_SOURCE')
    for rule in program.requirements:
        if rule.mandatory and (not rule.certain or not any(e.verified for e in rule.evidence)):
            reasons.add('UNKNOWN_TARGET_CONDITION')
    errors=[d.get('error_kind') for d in documents if d.get('extraction_status')!='SUCCESS']
    errors+=[metadata.get('error_kind')]
    errors+=[flag.get('kind') for flag in metadata.get('review_flags',[]) if isinstance(flag,dict)]
    for error in filter(None,errors):reasons.add(ERROR_REASONS.get(error,'OTHER_REVIEW_REQUIRED'))
    for doc in documents:
        if doc.get('fetch_status')!='SUCCESS':reasons.add('SOURCE_UNAVAILABLE')
        elif doc.get('extraction_status')!='SUCCESS' and not doc.get('error_kind'):reasons.add('DOCUMENT_PARSE_FAILED')
    drafts={d.get('content_hash') for d in metadata.get('document_ocr_reviews',[]) if d.get('draft',{}).get('review_required')}
    ocr_success=sum(bool(d.get('ocr_review',{}).get('review_required') or d.get('content_hash') in drafts) for d in documents)
    source_unavailable='SOURCE_UNAVAILABLE' in reasons
    useful=bool(raw_text.strip() or program.applicant_summary or any(d.get('extracted_text') for d in documents))
    state='ACTIONABLE' if not reasons else 'UNVERIFIABLE' if not program.evidence_complete and (source_unavailable or not useful) else 'NEEDS_REVIEW'
    metrics={'evidence_complete':program.evidence_complete,'program_status':program_status(program,at),
        'documents':len(documents),'download_success':sum(d.get('fetch_status')=='SUCCESS' for d in documents),
        'text_extraction_success':sum(d.get('extraction_status')=='SUCCESS' for d in documents),
        'document_failures':sum(d.get('extraction_status')!='SUCCESS' for d in documents),
        'ocr_required':sum(d.get('error_kind') in ('DOCUMENT_OCR_REQUIRED','DOCUMENT_OCR_REVIEW','DOCUMENT_OCR_SETUP') for d in documents),
        'ocr_success':ocr_success,'parse_failed':sum(d.get('error_kind') in ('DOCUMENT_PARSE','DOCUMENT_PROCESS','DOCUMENT_TIMEOUT','DOCUMENT_EMPTY') for d in documents),
        'too_large':sum(ERROR_REASONS.get(d.get('error_kind'))=='DOCUMENT_TOO_LARGE' for d in documents),
        'reviewed':sum(d.get('extraction_status')=='SUCCESS' for d in documents) if metadata.get('provider')=='source_review' and metadata.get('status')=='SUCCESS' else 0,
        'last_source_observation_at':last_seen_at.isoformat() if last_seen_at else None,
        'freshness':'INCIDENT' if not last_seen_at or at-last_seen_at>timedelta(hours=48) else 'WARNING' if 'STALE_SOURCE' in reasons else 'FRESH'}
    return {'state':state,'reasons':sorted(reasons),'metrics':metrics,'policy_version':VERSION}


def save_assessment(c,version_id,program,documents,metadata,raw_text):
    observed=c.execute('select last_observed_at at from startup_radar.program_versions where id=%s',(version_id,)).fetchone()['at']
    value=assess(program,documents or [],metadata,observed,raw_text=raw_text)
    c.execute('insert into startup_radar.program_quality(program_version_id,state,reasons,metrics,policy_version) values(%s,%s,%s,%s,%s) '
        'on conflict(program_version_id) do update set state=excluded.state,reasons=excluded.reasons,metrics=excluded.metrics,policy_version=excluded.policy_version,assessed_at=now()',
        (version_id,value['state'],value['reasons'],Jsonb(value['metrics']),VERSION))
    return value


def refresh_quality(db):
    assessed=0
    with db.transaction() as c:
        rows=c.execute('select v.* from startup_radar.programs p join startup_radar.program_versions v on v.id=p.current_version_id').fetchall()
        for row in rows:
            docs=c.execute('select * from startup_radar.documents where program_version_id=%s',(row['id'],)).fetchall()
            snapshots=c.execute('select distinct on(source_id) extraction_metadata from startup_radar.program_source_snapshots where program_version_id=%s order by source_id,observed_at desc,id desc',(row['id'],)).fetchall()
            metadata={'review_flags':[],'document_ocr_reviews':[]}
            for snapshot in snapshots:
                source=snapshot['extraction_metadata']
                metadata['review_flags'].extend(source.get('review_flags',[]))
                metadata['document_ocr_reviews'].extend(source.get('document_ocr_reviews',[]))
                if source.get('error_kind'):metadata['review_flags'].append({'kind':source['error_kind']})
                if source.get('provider')=='source_review' and source.get('status')=='SUCCESS':metadata.update(provider='source_review',status='SUCCESS')
            save_assessment(c,row['id'],Program.model_validate(row['normalized']),docs,metadata,row['raw_text'])
            assessed+=1
    return {'status':'SUCCESS','assessed':assessed,'policy_version':VERSION}


def quality_report(db,limit=100):
    at=now()
    with db.transaction() as c:
        rows=c.execute("select p.id,p.title,v.normalized,q.state,q.reasons,q.metrics,q.assessed_at,startup_radar.quality_projection(v.id) live_quality, "
            "coalesce((select max((m.recommendation->>'score')::numeric) from startup_radar.member_program_results m where m.program_version_id=v.id),0) relevance, "
            "array(select s.slug from startup_radar.program_sources ps join startup_radar.sources s on s.id=ps.source_id where ps.program_id=p.id) sources "
            'from startup_radar.programs p join startup_radar.program_versions v on v.id=p.current_version_id left join startup_radar.program_quality q on q.program_version_id=v.id').fetchall()
    counts=Counter();active_counts=Counter();pareto=Counter();source_counts={};queue=[];documents=Counter();backlog=Counter()
    for row in rows:
        p=Program.model_validate(row['normalized']);status=program_status(p,at);active=status in ('OPEN','UPCOMING');left=days_left(p,at)
        state=row['live_quality']['state'];reasons=row['live_quality']['reasons']
        counts[state]+=1;counts[status]+=1;counts['evidence_complete']+=p.evidence_complete
        if active:active_counts[state]+=1;active_counts['evidence_complete']+=p.evidence_complete
        pareto.update(reasons)
        for key in ('documents','download_success','text_extraction_success','document_failures','ocr_required','ocr_success','parse_failed','too_large','reviewed'):
            documents[key]+=(row['metrics'] or {}).get(key,0)
        for slug in row['sources']:
            source_counts.setdefault(slug,Counter()).update(total=1,evidence_complete=int(p.evidence_complete),active=int(active),active_evidence_complete=int(active and p.evidence_complete))
        if state!='ACTIONABLE':
            if active and left is not None and 0<=left<=7:backlog['d7']+=1
            if active and left is not None and 0<=left<=3:backlog['d3']+=1
            queue.append({'program_id':str(row['id']),'title':row['title'],'status':status,'quality_state':state,'reasons':reasons,
                'days_left':left,'relevance':float(row['relevance']),'assessed_at':row['assessed_at']})
    queue.sort(key=lambda r:(r['status'] not in ('OPEN','UPCOMING'),r['days_left'] if r['days_left'] is not None and r['days_left']>=0 else 100000,
                             -r['relevance'],tuple(r['reasons']),r['program_id']))
    return {'status':'SUCCESS','scope':'CURRENT_VERSIONS','total':len(rows),'counts':dict(counts),'open_upcoming':dict(active_counts),
        'current_documents':dict(documents),'reason_pareto':dict(pareto.most_common()),'review_backlog':dict(backlog),'sources':source_counts,'review_queue':queue[:limit]}
