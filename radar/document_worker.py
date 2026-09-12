"""Isolated attachment parser subprocess, with additional Linux resource limits."""
import json
import sys
from pathlib import Path


def main():
    try:
        if sys.platform!='win32':
            import resource
            resource.setrlimit(resource.RLIMIT_AS,(768*1024*1024,768*1024*1024))
            resource.setrlimit(resource.RLIMIT_CPU,(20,20))
        from radar.documents import extract_document
        path,filename,mime=sys.argv[1:4]
        kind,text=extract_document(Path(path).read_bytes(),filename,mime)
        result={'kind':kind,'text':text}
    except Exception as error:result={'error':str(error)[:300],'error_kind':getattr(error,'kind','DOCUMENT_PARSE')}
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
