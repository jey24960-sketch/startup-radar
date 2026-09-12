from radar.documents import extract_isolated,fetch_document
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
