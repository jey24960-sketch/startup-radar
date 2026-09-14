"""Bounded real-document OCR check. No production DB writes, AI or notifications."""
import argparse
import hashlib
import json
from pathlib import Path
import time
from core.clock import now
from radar.http import SafeHttp
from radar.ocr import extract_ocr_isolated
from radar.adapters.base import SourceFailure
from radar.documents import DocumentFailure

CORPUS=[
    {'id':'pre-wow-scanned','url':'https://www.k-startup.go.kr/afile/fileDownload/D7XLn','extension':'pdf',
     'sha256':'dfb0e133d143c19a02955beb7c5959ae980e1d7305620750092187e9225bf79b'},
    {'id':'gyeonggi-poster','url':'https://www.k-startup.go.kr/afile/fileDownload/B5XLn','extension':'png',
     'sha256':'07e9909362d46321ce9d6a9871bc43e356c13c1952e7e3a4699112477be282ee'},
    {'id':'bizinfo-scanned','url':'https://www.bizinfo.go.kr/cmm/fms/getImageFile.do?atchFileId=FILE_000000000773117&fileSn=1','extension':'pdf',
     'sha256':'e9ba4752569788c060eb82d25fbd4a60cd8aca9a5ac6264489377361c222e060'},
]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True);parser.add_argument('--model-dir',required=True)
    parser.add_argument('--input-directory',help='Previously acquired originals; hashes are still verified')
    args=parser.parse_args();folder=Path(args.output);folder.mkdir(parents=True,exist_ok=True)
    http=SafeHttp(['www.k-startup.go.kr','k-startup.go.kr','www.bizinfo.go.kr','bizinfo.go.kr'])
    report={'observed_at':now().isoformat(),'purpose':'VALIDATION_ONLY','items':[]}
    for item in CORPUS:
        row={**item};started=time.monotonic()
        try:
            if args.input_directory:
                data=(Path(args.input_directory)/(item['id']+'.'+item['extension'])).read_bytes()
                mime='application/pdf' if item['extension']=='pdf' else 'image/png'
            else:data,mime,final=http.get(item['url'])
            actual=hashlib.sha256(data).hexdigest()
            if actual!=item['sha256']:raise SourceFailure('CORPUS_CHANGED','Original content hash changed; inspect before accepting new golden evidence')
            path=folder/(item['id']+'.'+item['extension']);path.write_bytes(data)
            draft=extract_ocr_isolated(data,args.model_dir,folder/'cache')
            (folder/(item['id']+'.ocr.json')).write_text(json.dumps(draft,ensure_ascii=False,indent=2),encoding='utf-8')
            row.update(state='DRAFT_EXTRACTED',bytes=len(data),mime=mime,pages=draft['page_count'],
                       characters=sum(len(p['text']) for p in draft['pages']),review_required=draft['review_required'])
        except SourceFailure as error:row.update(state='SOURCE_FAILED',failure=error.record())
        except DocumentFailure as error:row.update(state='OCR_FAILED',reason_code=error.kind,message=str(error))
        row['latency_ms']=round((time.monotonic()-started)*1000);report['items'].append(row)
        print(json.dumps(row,ensure_ascii=False),flush=True)
    (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if all(row['state']=='DRAFT_EXTRACTED' for row in report['items']) else 1


if __name__=='__main__':raise SystemExit(main())
