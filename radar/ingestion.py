"""Source-isolated ingestion with typed health results and persistent raw evidence."""
import time
from uuid import uuid4
from psycopg.types.json import Jsonb
from radar.adapters.base import SourceFailure
from radar.adapters.official import KStartupApiAdapter,BizInfoApiAdapter
from radar.adapters.longtail import RssAdapter,HtmlAdapter,BrowserAdapter,SearchDiscoveryAdapter
from radar.http import SafeHttp
from radar.extraction import RequirementExtractor

ADAPTERS={'KSTARTUP':KStartupApiAdapter,'BIZINFO':BizInfoApiAdapter,'RSS':RssAdapter,'HTML':HtmlAdapter,
          'BROWSER':BrowserAdapter,'SEARCH':SearchDiscoveryAdapter}


def build_adapter(source):
    return ADAPTERS[source['adapter']](source,SafeHttp(source['config'].get('allowed_hosts',[])))


def ingest(db,sources=None,trigger='manual',adapter_factory=build_adapter,extractor=None):
    extractor=extractor or RequirementExtractor()
    with db.transaction() as c:
        run=c.execute("insert into radar.ingestion_runs(status,trigger_type) values('RUNNING',%s) returning id",(trigger,)).fetchone()['id']
        if sources is None:sources=c.execute('select * from radar.sources where enabled=true order by slug').fetchall()
    outcomes=[]
    for source in sources:
        started=time.monotonic();discovered=fetched=parsed=0;failures=[]
        with db.transaction() as c:c.execute('update radar.sources set last_attempted_at=now() where id=%s',(source['id'],))
        try:
            adapter=adapter_factory(source)
            for candidate in adapter.discover():
                discovered+=1
                try:
                    detail=adapter.fetch_detail(candidate);fetched+=1
                    documents=adapter.fetch_documents(detail)
                    for doc in documents:
                        if doc['extraction_status']!='SUCCESS':failures.append({'kind':doc.get('error_kind','DOCUMENT_PARSE'),'message':doc.get('error_message'),'url':doc['original_url']})
                    program=adapter.normalize(candidate,detail,documents)
                    try:program=extractor.extract(program,detail,documents,source['id'])
                    except SourceFailure as error:
                        program.evidence_complete=False
                        failures.append({'kind':error.kind,'message':error.message,'url':candidate.official_detail_url})
                    db.save_program(program,source['id'],candidate.source_program_id,candidate.discovery_url,candidate.raw_metadata,detail.text,documents)
                    parsed+=1
                except SourceFailure as error:failures.append({'kind':error.kind,'message':error.message,'url':candidate.official_detail_url})
                except Exception as error:failures.append({'kind':'NORMALIZE_OR_PERSIST','message':type(error).__name__,'url':candidate.official_detail_url})
        except SourceFailure as error:failures.append({'kind':error.kind,'message':error.message})
        except Exception as error:failures.append({'kind':'SOURCE_FAILURE','message':type(error).__name__})
        state=('PARTIAL' if parsed else 'FAILED') if failures else 'SUCCESS'
        outcome=dict(source_id=str(source['id']),status=state,discovered=discovered,fetched=fetched,parsed=parsed,failures=failures)
        with db.transaction() as c:
            c.execute('insert into radar.source_run_results(run_id,source_id,status,discovered_count,fetched_count,parsed_count,failures,latency_ms) '
                      'values(%s,%s,%s,%s,%s,%s,%s,%s)',(run,source['id'],state,discovered,fetched,parsed,Jsonb(failures),int((time.monotonic()-started)*1000)))
            if state=='SUCCESS':c.execute('update radar.sources set last_successful_at=now() where id=%s',(source['id'],))
        outcomes.append(outcome)
    if not outcomes:status='FAILED'
    elif all(o['status']=='SUCCESS' for o in outcomes):status='SUCCESS'
    elif any(o['status'] in ('SUCCESS','PARTIAL') for o in outcomes):status='PARTIAL_SUCCESS'
    else:status='FAILED'
    with db.transaction() as c:
        c.execute('update radar.ingestion_runs set status=%s,finished_at=now(),summary=%s where id=%s',
                  (status,Jsonb({'sources':outcomes,'message':'No enabled sources' if not outcomes else None}),run))
    return {'id':str(run),'status':status,'sources':outcomes}
