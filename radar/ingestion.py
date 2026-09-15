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
    return ADAPTERS[source['adapter']](source,SafeHttp(source['config'].get('allowed_hosts',[])))


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
            for candidate in adapter.discover():
                discovered+=1
                try:
                    if structured_only:
                        from radar.weekly import weekly_detail
                        if source['adapter'] not in ('KSTARTUP','BIZINFO'):raise ValueError('Weekly collection accepts official APIs only')
                        detail=weekly_detail(candidate);documents=[]
                    else:
                        detail=adapter.fetch_detail(candidate)
                        documents=adapter.fetch_documents(detail)
                    fetched+=1
                    for doc in documents:
                        if doc['extraction_status']!='SUCCESS':
                            failure=doc.get('failure') or SourceFailure(doc.get('error_kind','DOCUMENT_PARSE'),doc.get('error_message') or 'Document requires review').record(url=doc['original_url'])
                            failures.append({**failure,'stage':'DOCUMENT'})
                    program=adapter.normalize(candidate,detail,documents)
                    extraction_metadata={'provider':'structured_api_weekly' if structured_only else 'anthropic' if isinstance(extractor,RequirementExtractor) else 'injected',
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
            if coverage['pagination_complete'] and not coverage.get('weekly_policy') and parsed==discovered and not coverage.get('rejected_records') and not any(f.get('stage') not in ('DOCUMENT','EXTRACTION') for f in failures):
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
