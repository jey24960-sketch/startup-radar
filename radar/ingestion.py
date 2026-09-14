"""Source-isolated ingestion with typed health results and persistent raw evidence."""
import time
from uuid import uuid4
from psycopg.types.json import Jsonb
from radar.adapters.base import SourceFailure
from radar.adapters.official import KStartupApiAdapter,BizInfoApiAdapter
from radar.adapters.longtail import RssAdapter,HtmlAdapter,BrowserAdapter,SearchDiscoveryAdapter
from radar.http import SafeHttp
from radar.extraction import RequirementExtractor
from radar.analysis_cache import extract_cached

ADAPTERS={'KSTARTUP':KStartupApiAdapter,'BIZINFO':BizInfoApiAdapter,'RSS':RssAdapter,'HTML':HtmlAdapter,
          'BROWSER':BrowserAdapter,'SEARCH':SearchDiscoveryAdapter}


def build_adapter(source):
    if source['config'].get('opportunity_channel'):
        from radar.adapters.opportunities import OfficialChannelAdapter
        return OfficialChannelAdapter(source,SafeHttp(source['config'].get('allowed_hosts',[]),max_bytes=3_000_000,timeout=12))
    return ADAPTERS[source['adapter']](source,SafeHttp(source['config'].get('allowed_hosts',[])))


def candidates_with_watchlist(db,source,adapter):
    if not source['config'].get('opportunity_channel'):
        yield from adapter.discover();return
    from radar.adapters.base import Candidate
    seen=set()
    with db.transaction() as c:
        rows=c.execute("select s.official_detail_url,(array_agg(p.title order by s.last_seen_at desc))[1] title,max(s.last_seen_at) checked_at "
            "from startup_radar.program_sources s join startup_radar.programs p on p.id=s.program_id "
            "where s.source_id=%s and p.status in ('OPEN','UPCOMING','UNKNOWN') and (p.application_end_at is null or p.application_end_at>=now()) "
            "group by s.official_detail_url order by checked_at,s.official_detail_url limit 20",(source['id'],)).fetchall()
        submissions=c.execute("select official_url,description from startup_radar.opportunity_submissions where state='REVIEW' order by created_at limit 100").fetchall()
    from urllib.parse import urlsplit
    approved=set(source['config'].get('allowed_hosts',[]))
    # Only the same reviewed channel path; membership referrals cannot grant hosts.
    prefix=source['config'].get('submission_path_prefix')
    if prefix:
        for row in submissions[:20]:
            u=urlsplit(row['official_url'])
            if u.hostname in approved and u.path.startswith(prefix) and row['official_url'] not in seen:
                seen.add(row['official_url'])
                yield Candidate(source['slug'],row['official_url'],row['official_url'],row['official_url'],row['description'],{'referral':True})
    for row in rows:
        url=row['official_detail_url']
        if url in seen:continue
        seen.add(url)
        adapter.pagination.rechecks+=1
        yield Candidate(source['slug'],url,url,url,row['title'],{'active_recheck':True})
    for candidate in adapter.discover():
        if candidate.official_detail_url not in seen:
            seen.add(candidate.official_detail_url);yield candidate


def ingest(db,sources=None,trigger='manual',adapter_factory=build_adapter,extractor=None,structured_only=False):
    extractor=None if structured_only else extractor or RequirementExtractor()
    with db.transaction() as c:
        run=c.execute("insert into startup_radar.ingestion_runs(status,trigger_type) values('RUNNING',%s) returning id",(trigger,)).fetchone()['id']
        if sources is None:sources=c.execute('select * from startup_radar.sources where enabled=true order by slug').fetchall()
    outcomes=[];weekly_programs=[];new_programs=updated_programs=cache_hits=0
    for source in sources:
        started=time.monotonic();discovered=fetched=parsed=0;failures=[];adapter=None
        with db.transaction() as c:c.execute('update startup_radar.sources set last_attempted_at=now() where id=%s',(source['id'],))
        try:
            adapter=adapter_factory(source)
            for candidate in candidates_with_watchlist(db,source,adapter):
                discovered+=1
                try:
                    if structured_only:
                        from radar.weekly import weekly_detail
                        if source['adapter'] in ('KSTARTUP','BIZINFO'):detail=weekly_detail(candidate)
                        elif source['config'].get('opportunity_channel'):detail=adapter.fetch_detail(candidate)
                        else:raise ValueError('Structured collection requires an approved official channel')
                        documents=[]
                    else:
                        detail=adapter.fetch_detail(candidate)
                        documents=adapter.fetch_documents(detail)
                    fetched+=1
                    for doc in documents:
                        if doc['extraction_status']!='SUCCESS':
                            failure=doc.get('failure') or SourceFailure(doc.get('error_kind','DOCUMENT_PARSE'),doc.get('error_message') or 'Document requires review').record(url=doc['original_url'])
                            failures.append({**failure,'stage':'DOCUMENT'})
                    program=adapter.normalize(candidate,detail,documents)
                    if trigger=='daily-discovery' and source['adapter'] in ('KSTARTUP','BIZINFO'):
                        from radar.opportunity_store import attach_api_facts
                        attach_api_facts(program,detail,source)
                    extraction_metadata={'provider':('official_channel' if source['config'].get('opportunity_channel') else 'structured_api_weekly') if structured_only else 'anthropic' if isinstance(extractor,RequirementExtractor) else 'injected',
                        'model':getattr(extractor,'model',None),'schema_version':getattr(extractor,'version',None),'status':'SUCCESS'}
                    try:
                        if detail.evidence_warning:
                            extraction_metadata.update(provider='structured_api',model=None)
                            raise SourceFailure(detail.evidence_warning,'Official API facts retained; portal body unavailable, eligibility unverified')
                        from radar.program_review import resolve_review
                        try:reviewed=None if structured_only else resolve_review(db,source['id'],program,detail,documents,candidate.raw_metadata)
                        except ValueError:
                            raise SourceFailure('SOURCE_REVIEW_CHANGED','Reviewed supporting evidence changed; inspect the current source before reusing its decision')
                        if reviewed:
                            program,documents,extraction_metadata=reviewed
                        elif not structured_only:program=extract_cached(db,extractor,program,detail,documents,source['id'],extraction_metadata)
                    except SourceFailure as error:
                        program.evidence_complete=False
                        extraction_metadata.update(status='FAILED',error_kind=error.kind)
                        failures.append(error.record(stage='EXTRACTION',url=candidate.official_detail_url))
                    saved=db.save_program(program,source['id'],candidate.source_program_id,candidate.discovery_url,candidate.raw_metadata,detail.text,documents,extraction_metadata)
                    if program.opportunity:
                        from radar.opportunity_store import record_opportunity
                        record_opportunity(db,program,saved,source,detail)
                    new_programs+=saved['event']=='NEW';updated_programs+=saved['event']=='UPDATE'
                    cache_hits+=bool(extraction_metadata.get('cache_hit'))
                    parsed+=1
                    if structured_only:
                        from radar.weekly import snapshot
                        from radar.dates import program_status
                        weekly_programs.append({**saved,'snapshot':snapshot(program,candidate.raw_metadata),'status':program_status(program)})
                except SourceFailure as error:failures.append(error.record(url=candidate.official_detail_url))
                except Exception as error:failures.append(SourceFailure('NORMALIZE_OR_PERSIST',type(error).__name__).record(url=candidate.official_detail_url))
        except SourceFailure as error:failures.append(error.record())
        except Exception as error:failures.append(SourceFailure('SOURCE_FAILURE',type(error).__name__).record())
        state=('PARTIAL' if parsed else 'FAILED') if failures else 'SUCCESS'
        coverage=adapter.pagination.report() if getattr(adapter,'pagination',None) else {'scope':'CONFIGURED_LIST','pagination_complete':not any(f.get('stage') not in ('DOCUMENT','EXTRACTION') for f in failures)}
        coverage.update(persisted_records=parsed,failed_records=discovered-parsed)
        outcome=dict(source_id=str(source['id']),status=state,discovered=discovered,fetched=fetched,parsed=parsed,failures=failures,coverage=coverage)
        with db.transaction() as c:
            c.execute('insert into startup_radar.source_run_results(run_id,source_id,status,discovered_count,fetched_count,parsed_count,failures,latency_ms,coverage) '
                      'values(%s,%s,%s,%s,%s,%s,%s,%s,%s)',(run,source['id'],state,discovered,fetched,parsed,Jsonb(failures),int((time.monotonic()-started)*1000),Jsonb(coverage)))
            if state=='SUCCESS':c.execute('update startup_radar.sources set last_successful_at=now() where id=%s',(source['id'],))
            if parsed:c.execute('update startup_radar.sources set last_persisted_at=now(),last_source_observation_at=now() where id=%s',(source['id'],))
            if coverage['pagination_complete'] and parsed==discovered and not coverage.get('rejected_records') and not any(f.get('stage') not in ('DOCUMENT','EXTRACTION') for f in failures):
                c.execute('update startup_radar.sources set last_successful_full_scan_at=now() where id=%s',(source['id'],))
            if failures:c.execute('update startup_radar.sources set last_failure_at=now(),last_failure_reason=%s where id=%s',(failures[0].get('reason_code') or failures[0]['kind'],source['id']))
        outcomes.append(outcome)
    if not outcomes:status='FAILED'
    elif all(o['status']=='SUCCESS' for o in outcomes):status='SUCCESS'
    elif any(o['status'] in ('SUCCESS','PARTIAL') for o in outcomes):status='PARTIAL_SUCCESS'
    else:status='FAILED'
    with db.transaction() as c:
        c.execute('update startup_radar.ingestion_runs set status=%s,finished_at=now(),summary=%s where id=%s',
                  (status,Jsonb({'sources':outcomes,'new_programs':new_programs,'updated_programs':updated_programs,'analysis_cache_hits':cache_hits,'message':'No enabled sources' if not outcomes else None}),run))
    return {'id':str(run),'status':status,'sources':outcomes,**({'weekly_programs':weekly_programs} if structured_only else {})}
