"""Attachment evidence extraction with bounded file/zip/decompression limits."""
import hashlib
import io
import struct
import zipfile
import zlib
from pathlib import PurePosixPath
from bs4 import BeautifulSoup
from defusedxml import ElementTree
from pypdf import PdfReader
import olefile
from core.clock import now
from radar.adapters.base import SourceFailure

MAX_EXPANDED=40_000_000
MAX_TEXT=1_000_000


def html_text(data):
    soup=BeautifulSoup(data,'lxml')
    for node in soup(['script','style','nav','header','footer','noscript']):node.decompose()
    return soup.get_text('\n',strip=True)


def extract_zip(data,kind):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries=archive.infolist()
        if len(entries)>2000 or sum(e.file_size for e in entries)>MAX_EXPANDED: raise ValueError('Archive expansion limit')
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
            if len(raw)>MAX_EXPANDED:raise ValueError('HWP stream size limit')
            if flags&1:
                decoder=zlib.decompressobj(-15)
                raw=decoder.decompress(raw,MAX_EXPANDED+1)
                if len(raw)>MAX_EXPANDED or decoder.unconsumed_tail:raise ValueError('HWP expansion limit')
            total+=len(raw)
            if total>MAX_EXPANDED:raise ValueError('HWP expansion limit')
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
    if data.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):return 'hwp'
    if data.startswith(b'PK'):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names=z.namelist()
            if 'word/document.xml' in names:return 'docx'
            if any(n.startswith('Contents/section') for n in names):return 'hwpx'
        raise ValueError('Unrecognized ZIP document')
    if mime in ('text/html','application/xhtml+xml') and b'<' in data[:1000]:return 'html'
    raise ValueError('Unsupported or mismatched document type')


def extract_document(data,filename,mime):
    if len(data)>20_000_000:raise ValueError('File size limit')
    kind=detect_kind(data,filename,mime)
    if kind=='pdf':
        reader=PdfReader(io.BytesIO(data))
        if reader.is_encrypted:raise ValueError('Encrypted PDF')
        if len(reader.pages)>500:raise ValueError('PDF page limit')
        text='\n'.join(page.extract_text() or '' for page in reader.pages)
    elif kind in ('docx','hwpx'):text=extract_zip(data,kind)
    elif kind=='hwp':text=extract_hwp(data)
    else:text=html_text(data)
    if not text.strip():raise ValueError('No extractable text; OCR/manual review required')
    if len(text)>MAX_TEXT:raise ValueError('Extracted text limit; manual review required')
    return kind,text


def fetch_document(http,url,filename):
    result=dict(original_url=url,filename=filename,fetch_status='PENDING',extraction_status='PENDING')
    try:
        data,mime,final=http.get(url)
        result.update(fetch_status='SUCCESS',detected_mime=mime,content_hash=hashlib.sha256(data).hexdigest(),fetched_at=now().isoformat())
        try:
            kind,text=extract_document(data,filename,mime)
            result.update(extraction_status='SUCCESS',extracted_text=text,detected_mime=kind)
        except Exception as error:
            result.update(extraction_status='FAILED',error_kind='DOCUMENT_PARSE',error_message=str(error)[:300])
    except SourceFailure as error:
        result.update(fetch_status='BLOCKED' if error.kind in ('BLOCKED','ROBOTS_DENIED') else 'FAILED',
                      extraction_status='FAILED',error_kind=error.kind,error_message=error.message)
    return result
