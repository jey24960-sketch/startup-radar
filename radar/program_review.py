"""Explicit, source-bound review decisions; changed evidence invalidates reuse."""
import re
from urllib.parse import urlsplit
from pydantic import Field
from psycopg.types.json import Jsonb
from radar.models import StrictModel,Program
from radar.identity import digest
from radar.documents import fetch_document
from radar.http import SafeHttp
from radar.adapters.base import AcquiredDetail


class PageComparison(StrictModel):
    page: int = Field(ge=1,le=500)
    text_quote: str = Field(min_length=1,max_length=10000)
    review_note: str = Field(min_length=1,max_length=1000)


class DocumentCoverage(StrictModel):
    original_url: str
    original_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    text_document_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    page_count: int = Field(ge=1,le=500)
    pages: list[PageComparison] = Field(min_length=1,max_length=500)
    scope: str = 'ELIGIBILITY_AND_MATERIAL_TERMS'
    exclusions: str = Field(min_length=1,max_length=2000)


class ReviewDecision(StrictModel):
    primary_input_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    reviewed_program: Program
    coverage: list[DocumentCoverage] = Field(default_factory=list,max_length=50)
    supplemental_documents: list[dict] = Field(default_factory=list,max_length=5)
    reviewer_kind: str
    reviewer_label: str = Field(min_length=1,max_length=200)
    rationale: str = Field(min_length=20,max_length=10000)


def evidence_input_hash(source_id,detail,documents,raw_metadata):
    # OCR drafts/error descriptions and acquisition times are not official facts.
    return digest({'source_id':str(source_id),'url':detail.url,'text':detail.text,'official_metadata':raw_metadata,
        'documents':[{k:d.get(k) for k in ('original_url','content_hash','fetch_status','extraction_status','extracted_text')}
                     for d in sorted(documents,key=lambda d:d['original_url'])]})


def validate_decision(decision,source_id,detail,documents,raw_metadata,supplements=None):
    decision=ReviewDecision.model_validate(decision)
    if decision.reviewer_kind not in ('AGENT_VISUAL_REVIEW','OPERATOR_REVIEW'):
        raise ValueError('A review must identify its actual reviewer type')
    if decision.primary_input_hash!=evidence_input_hash(source_id,detail,documents,raw_metadata):
        raise ValueError('Official evidence changed; review the new source bundle')
    supplements=decision.supplemental_documents if supplements is None else supplements
    all_docs=[*documents,*supplements]
    if len({d['original_url'] for d in all_docs})!=len(all_docs):
        raise ValueError('Duplicate document URLs in reviewed evidence')
    evidence={str(source_id):detail.text}
    by_hash={d.get('content_hash'):d for d in all_docs if d.get('content_hash')}
    for doc in all_docs:
        if doc.get('fetch_status')!='SUCCESS':
            raise ValueError('A failed download cannot be covered by review')
        if doc.get('extraction_status')=='SUCCESS':
            if not doc.get('content_hash') or not doc.get('extracted_text'):
                raise ValueError('Readable evidence requires a hash and text')
            evidence[doc['content_hash']]=doc['extracted_text']
    compact=lambda value:re.sub(r'\s+',' ',value).strip()
    covered=set()
    for coverage in decision.coverage:
        original=by_hash.get(coverage.original_hash)
        if (not original or original['original_url']!=coverage.original_url
                or coverage.text_document_hash not in evidence
                or coverage.scope!='ELIGIBILITY_AND_MATERIAL_TERMS'):
            raise ValueError('Coverage must reference the exact original and a readable text alternative')
        if coverage.original_hash in covered or coverage.original_hash==coverage.text_document_hash:
            raise ValueError('Duplicate or circular document coverage')
        if [p.page for p in coverage.pages]!=list(range(1,coverage.page_count+1)):
            raise ValueError('Visual review must account for every page in order')
        for page in coverage.pages:
            if compact(page.text_quote) not in compact(evidence[coverage.text_document_hash]):
                raise ValueError('Page comparison quote is absent from the text alternative')
        covered.add(coverage.original_hash)
    if any(d.get('extraction_status')!='SUCCESS' and d.get('content_hash') not in covered for d in all_docs):
        raise ValueError('Critical unread document lacks explicit page coverage')
    program=decision.reviewed_program.model_copy(deep=True)
    if program.official_url!=detail.url:
        raise ValueError('Review cannot change the canonical official URL')
    if set(program.document_hashes)!={d['content_hash'] for d in all_docs}:
        raise ValueError('Reviewed program must retain every source document hash')
    for rule in program.requirements:
        if rule.mandatory and not rule.certain:
            raise ValueError('Do not approve an uncertain mandatory requirement')
        if rule.mandatory and rule.operator=='EXISTS':
            raise ValueError('Profile presence cannot substitute for a reviewed qualification')
        for citation in rule.evidence:
            key=citation.document_id or citation.source_id
            citation.verified=bool(compact(citation.text)) and key in evidence and compact(citation.text) in compact(evidence[key])
            citation.method='MANUAL'
            citation.confidence=1 if citation.verified else 0
            if citation.document_id:citation.source_id=str(source_id)
        if rule.mandatory and not any(e.verified for e in rule.evidence):
            raise ValueError('Every mandatory requirement needs a grounded source citation')
    if not program.evidence_complete:
        raise ValueError('This review path requires a complete decision, not a draft')
    if len(program.material_notes)>30 or any(len(note)>3000 for note in program.material_notes):
        raise ValueError('Material notes exceed review limits')
    program.document_coverage=[c.model_dump(mode='json') for c in decision.coverage]
    return program,all_docs


def resolve_review(db,source_id,program,detail,documents,raw_metadata):
    key=evidence_input_hash(source_id,detail,documents,raw_metadata)
    with db.transaction() as c:
        row=c.execute('select decision,revoked_at from startup_radar.program_reviews where input_hash=%s and source_id=%s order by created_at desc,id desc limit 1',
                      (key,source_id)).fetchone()
    if not row or row['revoked_at']:return None
    decision=ReviewDecision.model_validate(row['decision'])
    supplements=[]
    for expected in decision.supplemental_documents:
        url=expected['original_url'];parsed=urlsplit(url)
        if parsed.scheme!='https' or parsed.username or parsed.password:
            raise ValueError('Reviewed supplementary source must use public HTTPS')
        actual=fetch_document(SafeHttp([parsed.hostname]),url,expected['filename'])
        if (actual.get('content_hash')!=expected.get('content_hash') or actual.get('extraction_status')!='SUCCESS'
                or actual.get('extracted_text')!=expected.get('extracted_text')):
            # No AI fallback over a silently absent/changed approved supplement.
            raise ValueError('Reviewed supplementary evidence changed or is unavailable')
        supplements.append(actual)
    reviewed,all_docs=validate_decision(decision,source_id,detail,documents,raw_metadata,supplements)
    return reviewed,all_docs,{'provider':'source_review','status':'SUCCESS','input_hash':key,
        'reviewer_kind':decision.reviewer_kind,'reviewer_label':decision.reviewer_label,
        'review_flags':[],'review_rationale':decision.rationale,'cache_hit':True,
        'supplemental_urls':[d['original_url'] for d in supplements]}


def source_packet(db,program_id):
    with db.transaction() as c:
        version=c.execute('select v.* from startup_radar.program_versions v join startup_radar.programs p on p.current_version_id=v.id where p.id=%s',
                          (program_id,)).fetchone()
        if not version:raise LookupError('Program not found')
        snapshots=c.execute('select distinct on (source_id) * from startup_radar.program_source_snapshots '
            'where program_version_id=%s order by source_id,observed_at desc,id desc',(version['id'],)).fetchall()
        if len(snapshots)!=1:raise ValueError('Multi-source reviews need an explicit source selection')
        snapshot=snapshots[0]
        supplemental=set(snapshot['extraction_metadata'].get('supplemental_urls',[]))
        docs=c.execute('select original_url,filename,detected_mime,content_hash,fetch_status,extraction_status,extracted_text,error_kind,error_message,fetched_at '
                       'from startup_radar.documents where program_version_id=%s order by original_url',(version['id'],)).fetchall()
    return version,snapshot,[d for d in docs if d['original_url'] not in supplemental]


def apply_review(db,program_id,expected_version_id,decision):
    """Privileged worker operation. No browser can write the review registry."""
    from radar.scheduler import run_job
    decision=ReviewDecision.model_validate(decision)
    def execute(database,kind,**kwargs):
        version,snapshot,docs=source_packet(database,program_id)
        if str(version['id'])!=str(expected_version_id):raise ValueError('Review base version is stale')
        detail=AcquiredDetail(snapshot['official_detail_url'],version['raw_text'],version['normalized']['title'])
        program,all_docs=validate_decision(decision,snapshot['source_id'],detail,docs,snapshot['raw_metadata'])
        # Fetch every approved supplementary source now; no pasted replacement
        # text may masquerade as a fetched, reviewed document.
        fetched_supplements=[]
        for expected in decision.supplemental_documents:
            parsed=urlsplit(expected['original_url'])
            if parsed.scheme!='https' or parsed.username or parsed.password:raise ValueError('Invalid supplement URL')
            actual=fetch_document(SafeHttp([parsed.hostname]),expected['original_url'],expected['filename'])
            if actual.get('content_hash')!=expected.get('content_hash') or actual.get('extracted_text')!=expected.get('extracted_text'):
                raise ValueError('Supplement changed since review')
            fetched_supplements.append(actual)
        program,all_docs=validate_decision(decision,snapshot['source_id'],detail,docs,snapshot['raw_metadata'],fetched_supplements)
        metadata={'provider':'source_review','status':'SUCCESS','input_hash':decision.primary_input_hash,
                  'reviewer_kind':decision.reviewer_kind,'reviewer_label':decision.reviewer_label,
                  'review_flags':[],'review_rationale':decision.rationale,
                  'supplemental_urls':[d['original_url'] for d in decision.supplemental_documents]}
        # The reviewed version and reusable decision commit or roll back together.
        with database.transaction() as c:
            saved=database.save_program(program,snapshot['source_id'],snapshot['source_program_id'],snapshot['discovery_url'],
                snapshot['raw_metadata'],version['raw_text'],all_docs,metadata,expected_version_id=expected_version_id,connection=c,
                source_observed_at=version['last_observed_at'])
            row=c.execute('insert into startup_radar.program_reviews(input_hash,source_id,program_id,base_version_id,decision,reviewer_kind,reviewer_label) '
                'values(%s,%s,%s,%s,%s,%s,%s) returning id',(decision.primary_input_hash,snapshot['source_id'],program_id,
                expected_version_id,Jsonb(decision.model_dump(mode='json')),decision.reviewer_kind,decision.reviewer_label)).fetchone()
        return {'status':'SUCCESS','review_id':str(row['id']),'program_id':str(program_id),
                'version_id':str(saved['version_id']),'event':saved['event'],'delivery':'DISABLED','calculation':'PENDING_REFRESH'}
    return run_job(db,'INGEST',executor=execute)


def revoke_review(db,review_id,expected_version_id,note):
    from radar.scheduler import run_job
    if not 5<=len(note.strip())<=1000:raise ValueError('A review withdrawal needs an audit note')
    def execute(database,kind,**kwargs):
        with database.transaction() as c:
            review=c.execute('select * from startup_radar.program_reviews where id=%s',(review_id,)).fetchone()
        if not review:raise LookupError('Review not found')
        version,snapshot,docs=source_packet(database,review['program_id'])
        if str(version['id'])!=str(expected_version_id):raise ValueError('Program changed before review withdrawal')
        with database.transaction() as c:
            # Revoke the newest matching input decision too, so an older decision
            # cannot silently return if an operator selected its historical ID.
            c.execute('update startup_radar.program_reviews set revoked_at=coalesce(revoked_at,now()) '
                      'where input_hash=%s',(review['input_hash'],))
            if snapshot['extraction_metadata'].get('input_hash')!=review['input_hash']:
                return {'status':'SUCCESS','review_id':str(review_id),'scope':'REGISTRY_ONLY','delivery':'DISABLED'}
            program=Program.model_validate(version['normalized'])
            program.evidence_complete=False
            for rule in program.requirements:rule.certain=False
            program.document_coverage=[]
            docs=c.execute('select * from startup_radar.documents where program_version_id=%s',(version['id'],)).fetchall()
            saved=database.save_program(program,snapshot['source_id'],snapshot['source_program_id'],snapshot['discovery_url'],
                snapshot['raw_metadata'],version['raw_text'],docs,{'provider':'source_review','status':'REVOKED','review_note':note,
                'supplemental_urls':snapshot['extraction_metadata'].get('supplemental_urls',[]),
                'review_flags':[{'kind':'REVIEW_REVOKED','quotes':[]}]},expected_version_id=expected_version_id,connection=c,
                source_observed_at=version['last_observed_at'])
        return {'status':'SUCCESS','version_id':str(saved['version_id']),'review_id':str(review_id),
                'calculation':'PENDING_REFRESH','delivery':'DISABLED'}
    return run_job(db,'INGEST',executor=execute)
