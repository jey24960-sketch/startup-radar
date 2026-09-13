"""Bounded acquisition check using real adapters; no DB mutation or delivery."""
import json
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4
from radar.ingestion import build_adapter
from radar.adapters.base import SourceFailure
from core.clock import now


def main():
    report={'checked_at':now().isoformat(),'external_messages_sent':False,'sources':[]}
    registry=json.loads(Path('sources.json').read_text(encoding='utf-8'))
    for slug in ('kstartup','bizinfo','korea-startup-html'):
        source=next(row for row in registry if row['slug']==slug)
        source={**source,'id':str(uuid4())}
        result={'slug':slug,'source':source}
        try:
            adapter=build_adapter(source)
            candidate=next(iter(adapter.discover()),None)
            if candidate is None:
                result.update(status='EMPTY',discovered_sample=0)
            else:
                detail=adapter.fetch_detail(candidate)
                documents=adapter.fetch_documents(detail)
                program=adapter.normalize(candidate,detail,documents)
                program.evidence_complete=False
                result.update(status='ACQUIRED_WITHOUT_AI',candidate=asdict(candidate),
                              detail_text=detail.text,program=program.model_dump(mode='json'),documents=documents)
        except SourceFailure as error:
            result.update(status='FAILED',error_kind=error.kind,error_message=error.message)
        report['sources'].append(result)
    Path('work/live-shared-source-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps({'sources':[{'slug':r['slug'],'status':r['status'],'error_kind':r.get('error_kind'),
                                  'documents':len(r.get('documents',[]))} for r in report['sources']]},ensure_ascii=True))


if __name__=='__main__':main()
