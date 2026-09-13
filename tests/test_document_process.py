import io
import json
import subprocess
from types import SimpleNamespace
import pytest
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject,NumberObject
from radar.documents import DocumentFailure,extract_document,extract_isolated,fetch_document
from radar.adapters.longtail import HtmlAdapter
from radar.adapters.base import Candidate


def test_isolated_parser_extracts_and_retains_mime():
    class Http:
        def get(self,url):return b'<html><body><p>Public evidence</p></body></html>','text/html',url
    doc=fetch_document(Http(),'https://example.org/evidence','evidence.html')
    assert doc['extraction_status']=='SUCCESS' and doc['extracted_text']=='Public evidence'
    assert doc['detected_mime']=='text/html' and doc['content_hash']


def test_isolated_parser_failure_keeps_document_record():
    class Http:
        def get(self,url):return b'corrupt PDF','application/pdf',url
    doc=fetch_document(Http(),'https://example.org/notice.pdf','notice.pdf')
    assert doc['fetch_status']=='SUCCESS' and doc['extraction_status']=='FAILED'
    assert doc['error_kind']=='DOCUMENT_PARSE' and 'extracted_text' not in doc


def test_explicit_download_button_selector_parses_literal_only():
    class Http:
        def get(self,url):return b'''<main>Evidence</main><button class="download" onclick="window.location.href='/download?id=1'">notice.hwp</button><button class="download" onclick="runUntrustedCode()">bad.hwp</button>''','text/html',url
    adapter=HtmlAdapter({'slug':'fixture','config':{'document_selector':'button.download'}},Http())
    detail=adapter.fetch_detail(Candidate('fixture','1','https://example.org/list','https://example.org/notice','Fixture',{}))
    assert detail.document_urls==[('https://example.org/download?id=1','notice.hwp')]


def pdf_bytes(*page_types):
    writer=PdfWriter()
    for page_type in page_types:
        page=writer.add_blank_page(width=100,height=100)
        if page_type=='blank':continue
        content=DecodedStreamObject()
        if page_type=='text':
            font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),
                NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
            page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
            content.set_data(b'BT /F1 12 Tf 10 50 Td (Applicants must register.) Tj ET')
        else:
            picture=DecodedStreamObject()
            picture.set_data(b'\x00\x00\x00')
            picture.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Image'),
                NameObject('/Width'):NumberObject(1),NameObject('/Height'):NumberObject(1),
                NameObject('/ColorSpace'):NameObject('/DeviceRGB'),NameObject('/BitsPerComponent'):NumberObject(8)})
            page[NameObject('/Resources')]=DictionaryObject({NameObject('/XObject'):DictionaryObject({NameObject('/Scan'):writer._add_object(picture)})})
            content.set_data(b'q 100 0 0 100 0 0 cm /Scan Do Q')
        page[NameObject('/Contents')]=writer._add_object(content)
    buf=io.BytesIO();writer.write(buf)
    return buf.getvalue()


def test_mixed_pdf_cannot_silently_drop_scanned_eligibility_page():
    data=pdf_bytes('text','scan','blank')
    class Http:
        def get(self,url):return data,'application/octet-stream',url
    doc=fetch_document(Http(),'https://example.org/notice.pdf','notice.pdf')
    assert doc['fetch_status']=='SUCCESS' and doc['content_hash']
    assert doc['extraction_status']=='FAILED' and doc['error_kind']=='DOCUMENT_OCR_REQUIRED'
    assert 'text: 2;' in doc['error_message'] and 'extracted_text' not in doc


def test_text_pdf_with_truly_blank_page_remains_readable():
    kind,text=extract_isolated(pdf_bytes('blank','text'),'notice.pdf','application/pdf')
    assert kind=='pdf' and 'Applicants must register.' in text


@pytest.mark.parametrize('magic',[b'\x89PNG\r\n\x1a\n',b'\xff\xd8\xff'])
def test_image_signature_requires_review_even_with_misleading_name_or_mime(magic):
    with pytest.raises(DocumentFailure) as error:
        extract_isolated(magic+b'fixture','notice.pdf','application/octet-stream')
    assert error.value.kind=='DOCUMENT_OCR_REQUIRED'


def test_empty_pdf_is_distinct_from_image_only_pdf():
    with pytest.raises(DocumentFailure) as error:
        extract_document(pdf_bytes('blank'),'notice.pdf','application/pdf')
    assert error.value.kind=='DOCUMENT_EMPTY'
    with pytest.raises(DocumentFailure) as error:
        extract_document(pdf_bytes('scan'),'notice.pdf','application/pdf')
    assert error.value.kind=='DOCUMENT_OCR_REQUIRED'


def test_parser_timeout_is_reported_without_a_successful_document(monkeypatch):
    def timeout(*args,**kwargs):raise subprocess.TimeoutExpired('fixture',25)
    monkeypatch.setattr('radar.documents.subprocess.run',timeout)
    with pytest.raises(DocumentFailure) as error:
        extract_isolated(b'fixture','notice.txt','text/plain')
    assert error.value.kind=='DOCUMENT_TIMEOUT'


def test_pdf_text_limit_is_checked_before_reading_later_pages(monkeypatch):
    monkeypatch.setattr('radar.documents.MAX_TEXT',10)
    class Page:
        def extract_text(self):return 'More than ten characters'
    class Unvisited:
        def extract_text(self):pytest.fail('Reading must stop at the cumulative text limit')
    monkeypatch.setattr('radar.documents.PdfReader',lambda *_:SimpleNamespace(is_encrypted=False,pages=[Page(),Unvisited()]))
    with pytest.raises(DocumentFailure) as error:
        extract_document(b'%PDF-fixture','notice.pdf','application/pdf')
    assert error.value.kind=='DOCUMENT_LIMIT'


def test_unrecognized_worker_error_kind_falls_back_to_parse_failure(monkeypatch):
    monkeypatch.setattr('radar.documents.subprocess.run',lambda *args,**kwargs:SimpleNamespace(
        returncode=0,stdout='{"error":"bad file","error_kind":"UNTRUSTED_KIND"}'))
    with pytest.raises(DocumentFailure) as error:
        extract_isolated(b'fixture','notice.txt','text/plain')
    assert error.value.kind=='DOCUMENT_PARSE'


def test_model_complete_claim_cannot_override_unread_pdf_page():
    from radar.adapters.base import AcquiredDetail
    from radar.extraction import RequirementExtractor
    from radar.models import Program,TeamProfile
    from radar.eligibility import evaluate
    data=pdf_bytes('text','scan')
    class Http:
        def get(self,url):return data,'application/pdf',url
    document=fetch_document(Http(),'https://example.org/notice.pdf','notice.pdf')
    text='누구나 신청 가능합니다.'
    payload={'requirements':[],'program_types':['EDUCATION'],'eligibility_section_quote':text,'evidence_complete':True}
    client=SimpleNamespace(messages=SimpleNamespace(create=lambda **kwargs:SimpleNamespace(
        content=[SimpleNamespace(type='text',text=json.dumps(payload))])))
    program=Program(title='Fixture',organization='Fixture',official_url='https://example.org/notice')
    result=RequirementExtractor(client).extract(program,AcquiredDetail(program.official_url,text,program.title),[document],'source')
    assert not result.evidence_complete
    assert evaluate(TeamProfile(),result.requirements,result.evidence_complete).status=='UNVERIFIABLE'
