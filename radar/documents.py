"""Attachment evidence extraction with bounded file/zip/decompression limits."""
import hashlib
import io
import struct
import zipfile
import zlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from pathlib import PurePosixPath
from bs4 import BeautifulSoup
from defusedxml import ElementTree
from pypdf import PdfReader
import olefile
from core.clock import now
from radar.adapters.base import SourceFailure

MAX_EXPANDED=40_000_000
MAX_TEXT=1_000_000
DOCUMENT_FAILURE_KINDS=frozenset({
    'DOCUMENT_PARSE','DOCUMENT_OCR_REQUIRED','DOCUMENT_EMPTY','DOCUMENT_LIMIT',
    'DOCUMENT_TIMEOUT','DOCUMENT_PROCESS','DOCUMENT_OCR_REVIEW','DOCUMENT_OCR_SETUP',
})


class DocumentFailure(ValueError):
    """An actionable parser failure that survives the subprocess boundary."""
    def __init__(self,kind,message):
        self.kind=kind if kind in DOCUMENT_FAILURE_KINDS else 'DOCUMENT_PARSE'
        super().__init__(message)


def html_text(data):
    soup=BeautifulSoup(data,'lxml')
    for node in soup(['script','style','nav','header','footer','noscript']):node.decompose()
    return soup.get_text('\n',strip=True)


def extract_zip(data,kind):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries=archive.infolist()
        if len(entries)>2000 or sum(e.file_size for e in entries)>MAX_EXPANDED: raise DocumentFailure('DOCUMENT_LIMIT','Archive expansion limit')
        if any(e.flag_bits & 1 for e in entries): raise ValueError('Encrypted archive')
        names=archive.namelist()
        if kind=='docx': targets=[n for n in names if n=='word/document.xml']
        else: targets=sorted(n for n in names if n.startswith('Contents/section') and n.endswith('.xml'))
        if not targets:raise ValueError('Expected document XML missing')
        texts=[]
        for name in targets:
            root=ElementTree.fromstring(archive.read(name))
            texts.extend(e.text for e in root.iter() if e.tag.split('}')[-1]=='t' and e.text)
        return '\n'.join(texts)


def extract_hwp(data):
    with olefile.OleFileIO(io.BytesIO(data)) as doc:
        header=doc.openstream('FileHeader').read(256)
        if not header.startswith(b'HWP Document File'):raise ValueError('Not HWP')
        flags=struct.unpack_from('<I',header,36)[0]
        if flags & (2|4):raise ValueError('Encrypted/distribution HWP unsupported')
        texts=[];total=0
        for path in doc.listdir():
            if len(path)!=2 or path[0]!='BodyText' or not path[1].startswith('Section'):continue
            raw=doc.openstream(path).read(MAX_EXPANDED+1)
            if len(raw)>MAX_EXPANDED:raise DocumentFailure('DOCUMENT_LIMIT','HWP stream size limit')
            if flags&1:
                decoder=zlib.decompressobj(-15)
                raw=decoder.decompress(raw,MAX_EXPANDED+1)
                if len(raw)>MAX_EXPANDED or decoder.unconsumed_tail:raise DocumentFailure('DOCUMENT_LIMIT','HWP expansion limit')
            total+=len(raw)
            if total>MAX_EXPANDED:raise DocumentFailure('DOCUMENT_LIMIT','HWP expansion limit')
            pos=0
            while pos+4<=len(raw):
                word=struct.unpack_from('<I',raw,pos)[0];pos+=4
                tag=word&1023;length=(word>>20)&4095
                if length==4095:
                    length=struct.unpack_from('<I',raw,pos)[0];pos+=4
                if pos+length>len(raw):raise ValueError('Truncated HWP record')
                if tag==67:
                    text=raw[pos:pos+length].decode('utf-16le',errors='strict')
                    texts.append(''.join(c for c in text if c.isprintable() or c in '\n\t'))
                pos+=length
        return '\n'.join(texts)


def detect_kind(data,filename,mime):
    suffix=PurePosixPath(filename.lower()).suffix
    if data.startswith(b'%PDF-'):return 'pdf'
    if data.startswith(b'\x89PNG\r\n\x1a\n') or data.startswith(b'\xff\xd8\xff'):
        raise DocumentFailure('DOCUMENT_OCR_REQUIRED','Image attachment requires OCR and evidence review')
    if data.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):return 'hwp'
    if data.startswith(b'PK'):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names=z.namelist()
            if 'word/document.xml' in names:return 'docx'
            if any(n.startswith('Contents/section') for n in names):return 'hwpx'
        raise ValueError('Unrecognized ZIP document')
    if mime in ('text/html','application/xhtml+xml') and b'<' in data[:1000]:return 'html'
    if suffix=='.txt' and mime in ('text/plain','application/octet-stream'):return 'txt'
    raise ValueError('Unsupported or mismatched document type')


def extract_pdf(data):
    reader=PdfReader(io.BytesIO(data))
    if reader.is_encrypted:raise ValueError('Encrypted PDF')
    if len(reader.pages)>500:raise DocumentFailure('DOCUMENT_LIMIT','PDF page limit')
    texts=[];unread_pages=[];total=0
    for number,page in enumerate(reader.pages,1):
        text=page.extract_text() or ''
        total+=len(text)+1
        if total>MAX_TEXT:raise DocumentFailure('DOCUMENT_LIMIT','Extracted text limit; manual review required')
        texts.append(text)
        if not text.strip():
            # A blank page with no drawing content is harmless. A nonempty stream
            # may contain a scan, outlined text or other unread evidence. Never
            # certify the whole file merely because another page yielded text.
            content=page.get_contents()
            if (content is not None and content.get_data().strip()) or page.get('/Annots'):
                unread_pages.append(number)
    if unread_pages:
        pages=', '.join(map(str,unread_pages[:12]))+(' …' if len(unread_pages)>12 else '')
        raise DocumentFailure('DOCUMENT_OCR_REQUIRED',f'PDF pages with content but no readable text: {pages}; OCR/manual review required')
    return '\n'.join(texts)


def extract_document(data,filename,mime):
    if len(data)>20_000_000:raise DocumentFailure('DOCUMENT_LIMIT','File size limit')
    kind=detect_kind(data,filename,mime)
    if kind=='pdf':text=extract_pdf(data)
    elif kind in ('docx','hwpx'):text=extract_zip(data,kind)
    elif kind=='hwp':text=extract_hwp(data)
    elif kind=='txt':
        text=data.decode('utf-8-sig',errors='strict')
        if any(ord(c)<32 and c not in '\r\n\t' for c in text):raise ValueError('Binary control characters in text attachment')
    else:text=html_text(data)
    if not text.strip():raise DocumentFailure('DOCUMENT_EMPTY','No extractable text; manual review required')
    if len(text)>MAX_TEXT:raise DocumentFailure('DOCUMENT_LIMIT','Extracted text limit; manual review required')
    return kind,text


def fetch_document(http,url,filename):
    result=dict(original_url=url,filename=filename,fetch_status='PENDING',extraction_status='PENDING')
    try:
        data,mime,final=http.get(url)
        result.update(fetch_status='SUCCESS',detected_mime=mime,content_hash=hashlib.sha256(data).hexdigest(),fetched_at=now().isoformat())
        try:
            kind,text=extract_isolated(data,filename,mime)
            result.update(extraction_status='SUCCESS',extracted_text=text)
        except DocumentFailure as error:
            result.update(extraction_status='FAILED',error_kind=error.kind,error_message=str(error)[:300])
            if error.kind=='DOCUMENT_OCR_REQUIRED' and os.environ.get('RADAR_OCR_MODEL_DIR'):
                try:
                    from radar.ocr import extract_ocr_isolated
                    draft=extract_ocr_isolated(data,os.environ['RADAR_OCR_MODEL_DIR'],os.environ.get('RADAR_OCR_CACHE_DIR'))
                    result.update(ocr_review=draft,error_kind='DOCUMENT_OCR_REVIEW',
                                  error_message='OCR draft available; compare every page with the original before eligibility use')
                except DocumentFailure as ocr_error:
                    result.update(error_kind=ocr_error.kind,error_message=str(ocr_error)[:300])
                except Exception:
                    result.update(error_kind='DOCUMENT_PROCESS',error_message='OCR review processing failed')
        except Exception as error:
            result.update(extraction_status='FAILED',error_kind='DOCUMENT_PARSE',error_message=str(error)[:300])
    except SourceFailure as error:
        result.update(fetch_status='BLOCKED' if error.kind in ('BLOCKED','ROBOTS_DENIED') else 'FAILED',
                      extraction_status='FAILED',error_kind=error.kind,error_message=error.message)
    return result


def extract_isolated(data,filename,mime,timeout=25):
    """Keep native/parser failures and runaway CPU outside the ingestion process."""
    if len(data)>20_000_000:raise DocumentFailure('DOCUMENT_LIMIT','File size limit')
    with tempfile.TemporaryDirectory(prefix='radar-document-') as folder:
        path=Path(folder)/'document.bin';path.write_bytes(data)
        env={k:v for k,v in os.environ.items() if k in ('PATH','SYSTEMROOT','WINDIR','TEMP','TMP')}
        env['PYTHONIOENCODING']='utf-8'
        try:
            result=subprocess.run([sys.executable,'-m','radar.document_worker',str(path),filename,mime],
                cwd=Path(__file__).resolve().parent.parent,env=env,capture_output=True,text=True,encoding='utf-8',timeout=timeout)
        except subprocess.TimeoutExpired:raise DocumentFailure('DOCUMENT_TIMEOUT','Document parser time limit exceeded')
        if result.returncode:raise DocumentFailure('DOCUMENT_PROCESS','Document parser process failed or resource limit exceeded')
        parsed=json.loads(result.stdout)
        if parsed.get('error'):raise DocumentFailure(parsed.get('error_kind','DOCUMENT_PARSE'),parsed['error'])
        return parsed['kind'],parsed['text']
