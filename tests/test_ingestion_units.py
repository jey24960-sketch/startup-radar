import io,json,zipfile
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from radar.adapters.base import SourceFailure,Candidate,AcquiredDetail
from radar.adapters.official import KStartupApiAdapter,BizInfoApiAdapter
from radar.adapters.longtail import RssAdapter,HtmlAdapter,SearchDiscoveryAdapter
from radar.documents import extract_document,fetch_document
from radar.extraction import RequirementExtractor
from radar.models import Program


def source(adapter='RSS'):
    return {'id':'fixture-source','slug':'fixture','name':'Official fixture','adapter':adapter,
            'config':{'url':'https://example.org/feed','link_selector':'a.notice'}}


def http(payload):
    data=payload.encode() if isinstance(payload,str) else json.dumps(payload).encode()
    return SimpleNamespace(get=Mock(return_value=(data,'application/json','https://example.org/feed')))


def test_rss_preserves_each_notice_url():
    adapter=RssAdapter(source(),http('<rss><channel><item><guid>1</guid><title>창업지원</title><link>https://example.org/notice/1</link></item></channel></rss>'))
    candidate=list(adapter.discover())[0]
    assert candidate.discovery_url=='https://example.org/notice/1' and candidate.source_program_id=='1'
    assert candidate.raw_metadata['feed_url']=='https://example.org/feed'


def test_atom_href():
    xml='<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>x</id><title>Startup</title><link href="https://example.org/1"/></entry></feed>'
    assert list(RssAdapter(source(),http(xml)).discover())[0].official_detail_url=='https://example.org/1'


def test_html_list_detail_and_attachment():
    h=http('<a class="notice" href="/one">First</a><a class="notice" href="/two">Second</a>')
    a=HtmlAdapter(source('HTML'),h);candidates=list(a.discover())
    assert len({c.discovery_url for c in candidates})==2
    h.get.return_value=(b'<main><h1>Notice</h1><p>Eligible founders</p><a href="/notice.pdf">notice.pdf</a></main>','text/html','https://example.org/one')
    detail=a.fetch_detail(candidates[0])
    assert detail.document_urls==[('https://example.org/notice.pdf','notice.pdf')]
    assert 'Eligible founders' in detail.text


def test_search_without_provider_is_explicitly_disabled():
    with pytest.raises(SourceFailure,match='NOT_CONFIGURED'):list(SearchDiscoveryAdapter(source(),http('')).discover())


def test_html_repeated_image_anchor_preserves_notice_title():
    adapter=HtmlAdapter(source('HTML'),http('<a class="notice" href="/one"><img src="pic"></a><a class="notice" href="/one">Notice title</a>'))
    rows=list(adapter.discover())
    assert len(rows)==1 and rows[0].title=='Notice title'


def test_verified_literal_navigation_mapping_never_executes_javascript():
    config=source('HTML')
    config['config'].update(javascript_link_pattern=r"javascript:viewNotice\('(?P<bbs>[A-Z0-9]+)',\s*'(?P<board>[0-9]+)',\s*'(?P<menu>[0-9]+)'\)",
        javascript_url_template='/user/bbs/{bbs}/view.do?boardId={board}&menuNo={menu}',source_program_id_template='{bbs}:{board}',
        detail_selector='article',detail_title_selector='h2')
    h=http('''<a class="notice" href="javascript:viewNotice('BMSR00052', '553110', '15200048')">Listing text with extra summary</a>
      <a class="notice" href="javascript:alert('unsafe')">Skip</a>
      <a class="notice" href="javascript:viewNotice('BMSR00052', '553110', '15200048');alert(1)">Skip</a>''')
    adapter=HtmlAdapter(config,h);rows=list(adapter.discover())
    assert len(rows)==1 and rows[0].source_program_id=='BMSR00052:553110'
    assert rows[0].official_detail_url=='https://example.org/user/bbs/BMSR00052/view.do?boardId=553110&menuNo=15200048'
    h.get.return_value=(b'<article><header><h2>Exact title</h2></header><p>Body</p></article>','text/html',rows[0].official_detail_url)
    detail=adapter.fetch_detail(rows[0])
    assert adapter.normalize(rows[0],detail,[]).title=='Exact title'


def test_corrupted_notice_text_is_an_explicit_failure():
    h=http('<main>지원 조건 \ufffd\ufffd\ufffd</main>');adapter=HtmlAdapter(source('HTML'),h)
    candidate=Candidate('fixture','1','https://example.org/1','https://example.org/1','Notice')
    with pytest.raises(SourceFailure,match='DETAIL_ENCODING'):adapter.fetch_detail(candidate)


def test_official_empty_vs_error(monkeypatch):
    monkeypatch.setenv('KSTARTUP_API_KEY','fixture-key')
    assert list(KStartupApiAdapter(source('KSTARTUP'),http({'data':{'data':[]},'totalCount':0})).discover())==[]
    with pytest.raises(SourceFailure,match='API_SCHEMA'):
        list(KStartupApiAdapter(source('KSTARTUP'),http({'error':'Invalid key'})).discover())


def test_pdf_nul_text_is_retained_as_document_failure_not_database_error(monkeypatch):
    from radar import documents
    monkeypatch.setattr(documents,'extract_pdf',lambda data:'대상\x00제외 조건')
    with pytest.raises(documents.DocumentFailure,match='NUL') as error:
        extract_document(b'%PDF-corrupt-font','notice.pdf','application/pdf')
    assert error.value.kind=='DOCUMENT_PARSE'


def test_pdf_valid_unicode_text_is_not_rewritten(monkeypatch):
    from radar import documents
    text='신청 대상: 예비창업자\n조건 70% 이상'
    monkeypatch.setattr(documents,'extract_pdf',lambda data:text)
    assert extract_document(b'%PDF-valid-text','notice.pdf','application/pdf')==('pdf',text)


def test_html_line_endings_are_stable_without_changing_words():
    from radar.documents import html_text
    assert html_text('<p>조건 A\r\n조건 B\r조건 C</p>')==html_text('<p>조건 A\n조건 B\n조건 C</p>')


def test_missing_kstartup_portal_body_retains_only_unverified_api_facts():
    row={'pbanc_sn':179197,'biz_pbanc_nm':'Official program','pbanc_ctnt':'Official summary',
         'detl_pg_url':'https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=179197'}
    candidate=Candidate('kstartup','179197',row['detl_pg_url'],row['detl_pg_url'],row['biz_pbanc_nm'],row)
    a=KStartupApiAdapter(source('KSTARTUP'),http('<body><a>skip</a></body>'))
    detail=a.fetch_detail(candidate)
    assert detail.evidence_warning=='DETAIL_UNAVAILABLE'
    assert detail.text=='Official summary' and not detail.document_urls
    assert not a.normalize(candidate,detail,[]).evidence_complete
    a.http.get=Mock(side_effect=SourceFailure('BLOCKED','Access denied'))
    with pytest.raises(SourceFailure,match='BLOCKED'):a.fetch_detail(candidate)


def test_kstartup_documented_fields(monkeypatch):
    monkeypatch.setenv('KSTARTUP_API_KEY','fixture-key')
    row={'pbanc_sn':123,'biz_pbanc_nm':'Official title','biz_aply_url':'https://example.org/detail','detl_pg_url':'https://example.org/apply',
         'pbanc_ntrp_nm':'Agency','pbanc_rcpt_bgng_dt':'20260901','pbanc_rcpt_end_dt':'20261001'}
    adapter=KStartupApiAdapter(source('KSTARTUP'),http({'data':{'data':[row]},'totalCount':1}))
    candidate=list(adapter.discover())[0]
    program=adapter.normalize(candidate,AcquiredDetail(candidate.official_detail_url,'text',candidate.title),[])
    assert candidate.source_program_id=='123' and program.application_url=='https://example.org/apply'
    assert program.application_end_at.hour==23 and program.application_end_at.utcoffset().total_seconds()==9*3600
    assert program.application_end_precision=='DATE'
    assert not program.evidence_complete


@pytest.mark.parametrize('key',['fixture+key/value==','fixture%2Bkey%2Fvalue%3D%3D'])
def test_kstartup_encoded_and_decoded_keys_share_one_wire_encoding(monkeypatch,key):
    import requests
    monkeypatch.setenv('KSTARTUP_API_KEY',key)
    client=http({'data':[],'totalCount':0})
    assert list(KStartupApiAdapter(source('KSTARTUP'),client).discover())==[]
    params=client.get.call_args.kwargs['params']
    assert params['serviceKey']=='fixture+key/value=='
    prepared=requests.Request('GET',KStartupApiAdapter.endpoint,params=params).prepare()
    assert 'serviceKey=fixture%2Bkey%2Fvalue%3D%3D' in prepared.url
    assert '%252B' not in prepared.url


@pytest.mark.parametrize('value',['20260914 ~ 20260930','2026-09-14 ~ 2026-09-30','2026.09.14 ~ 2026.09.30'])
def test_bizinfo_live_calendar_range(value):
    from radar.adapters.official import parse_period
    start,end=parse_period(value)
    assert start.date().isoformat()=='2026-09-14' and end.date().isoformat()=='2026-09-30'
    assert start.hour==0 and end.hour==23 and end.utcoffset().total_seconds()==9*3600


@pytest.mark.parametrize('value',[None,'예산 소진시','2026-09-31 ~ 2026-10-02','2026-09-30 ~ 2026-09-14','2026-09-14 ~ 미정'])
def test_bizinfo_unknown_or_invalid_period_never_fabricates_date(value):
    from radar.adapters.official import parse_period
    assert parse_period(value)==(None,None)


@pytest.mark.parametrize('guide',[None,'forms.gle/public-form','startup.example.org/'])
def test_live_kstartup_null_detail_field_uses_verified_portal_notice(monkeypatch,guide):
    monkeypatch.setenv('KSTARTUP_API_KEY','fixture-key')
    url='https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=179222'
    row={'pbanc_sn':179222,'biz_pbanc_nm':'Current notice','biz_aply_url':None,'biz_gdnc_url':guide,'detl_pg_url':url}
    adapter=KStartupApiAdapter(source('KSTARTUP'),http({'data':[row],'totalCount':1}))
    candidate=list(adapter.discover())[0]
    assert candidate.official_detail_url==url
    program=adapter.normalize(candidate,AcquiredDetail(url,'Actual notice',candidate.title),[])
    assert program.official_url==url and program.application_url is None


def test_kstartup_download_controls_preserve_unsupported_attachments():
    url='https://www.k-startup.go.kr/web/contents/bizpbanc-ongoing.do?schM=view&pbancSn=179222'
    metadata={'pbanc_sn':179222,'detl_pg_url':url}
    markup='''<header>Unrelated portal content</header><div class="app_notice_details-wrap">
      <p>Eligibility section</p><div class="board_file"><ul>
      <li class="clear"><a class="file_bg">poster.jpg</a><div><ul><li>
      <a name="downloadBtn" href="/afile/fileDownload/abc"><span>다운로드</span></a>
      </li></ul></div></li></ul></div></div>'''
    client=http(markup)
    client.get.return_value=(markup.encode(),'text/html',url)
    candidate=Candidate('fixture','179222',url,url,'Notice',metadata)
    detail=KStartupApiAdapter(source('KSTARTUP'),client).fetch_detail(candidate)
    assert detail.document_urls==[('https://www.k-startup.go.kr/afile/fileDownload/abc','poster.jpg')]
    assert 'Eligibility section' in detail.text and 'Unrelated portal content' not in detail.text


def test_kstartup_period_time_is_saved_before_ai_and_matches_api_calendar():
    from radar.adapters.official import kstartup_period_time
    from radar.dates import korean_date
    text='신청기간\n2026.09.09(수) 09:00 ~ 2026.09.30(수) 17:00 까지\n신청방법\n온라인'
    day,precision=kstartup_period_time(korean_date('20260930',True),text)
    assert precision=='DATETIME' and (day.hour,day.minute)==(17,0)
    unchanged,precision=kstartup_period_time(korean_date('20261001',True),text)
    assert precision=='DATE' and unchanged.hour==23
    _,precision=kstartup_period_time(korean_date('20260930',True),'행사일시\n2026.09.30(수) 17:00')
    assert precision=='DATE'
    _,precision=kstartup_period_time(korean_date('20260930',True),text+'\n접수기간\n2026.09.30(수) 18:00')
    assert precision=='DATE'


def test_bizinfo_documented_fields(monkeypatch):
    monkeypatch.setenv('BIZINFO_API_KEY','fixture-key')
    row={'seq':'PBLN1','title':'지원사업','link':'https://example.org/1','author':'Agency','reqstDt':'20260901 ~ 20260930'}
    adapter=BizInfoApiAdapter(source('BIZINFO'),http({'jsonArray':{'item':[row]}}))
    candidate=list(adapter.discover())[0]
    p=adapter.normalize(candidate,AcquiredDetail(candidate.official_detail_url,'text',candidate.title),[])
    assert p.title=='지원사업' and p.application_end_at.day==30
    assert p.application_end_precision=='DATE'


def test_missing_credentials_explicit(monkeypatch):
    monkeypatch.delenv('KSTARTUP_API_KEY',raising=False)
    with pytest.raises(SourceFailure,match='MISSING_CREDENTIAL'):list(KStartupApiAdapter(source(),http('')).discover())


def test_bizinfo_multiple_attachments_keep_file_names_and_separate_downloads():
    metadata={'flpthNm':'https://example.org/file?id=1@https://example.org/file?id=2',
              'fileNm':'신청서.hwp@증빙서류.hwpx',
              'printFlpthNm':'/notice.pdf','printFileNm':'공고문.pdf'}
    candidate=Candidate('fixture','1','https://example.org/1','https://example.org/1','Notice',metadata)
    adapter=BizInfoApiAdapter(source('BIZINFO'),http('<main>Notice</main>'))
    detail=adapter.fetch_detail(candidate)
    assert detail.document_urls==[('https://example.org/file?id=1','신청서.hwp'),
        ('https://example.org/file?id=2','증빙서류.hwpx'),('https://example.org/notice.pdf','공고문.pdf')]


def test_bizinfo_missing_attachment_names_do_not_shift_other_names():
    metadata={'flpthNm':'/one@/two@/three','fileNm':'@second.hwp'}
    candidate=Candidate('fixture','1','https://example.org/1','https://example.org/1','Notice',metadata)
    detail=BizInfoApiAdapter(source('BIZINFO'),http('<main>Notice</main>')).fetch_detail(candidate)
    assert detail.document_urls==[('https://example.org/one','attachment'),
        ('https://example.org/two','second.hwp'),('https://example.org/three','attachment')]


@pytest.mark.parametrize('kind,path', [('docx','word/document.xml'),('hwpx','Contents/section0.xml')])
def test_xml_document_extractors(kind,path):
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w') as z:z.writestr(path,'<root><p><t>예비창업자 신청 가능</t></p></root>')
    detected,text=extract_document(buf.getvalue(),'notice.'+kind,'application/zip')
    assert detected==kind and '예비창업자' in text


def test_official_utf8_text_attachment_with_binary_download_mime():
    kind,text=extract_document('지원대상: 서울시 소재 스타트업'.encode('utf-8-sig'),'poster.txt','application/octet-stream')
    assert kind=='txt' and text=='지원대상: 서울시 소재 스타트업'
    with pytest.raises(ValueError,match='control characters'):
        extract_document(b'hello\x00world','poster.txt','application/octet-stream')
    with pytest.raises(UnicodeDecodeError):
        extract_document(b'\xff\xff','poster.txt','text/plain')


@pytest.mark.parametrize('filename',['notice.pdf','notice.hwp','notice.hwpx'])
def test_document_failure_retains_metadata(filename):
    result=fetch_document(http('this is not a document'),'https://example.org/doc',filename)
    assert result['filename']==filename and result['fetch_status']=='SUCCESS'
    assert result['extraction_status']=='FAILED' and result['content_hash']
    assert 'extracted_text' not in result


def test_malformed_extraction_and_fake_evidence():
    p=Program(title='Notice',organization='Org',official_url='https://example.org/1')
    detail=AcquiredDetail(p.official_url,'원문에는 조건이 없습니다','Notice')
    mock=SimpleNamespace(messages=SimpleNamespace(create=Mock(return_value=SimpleNamespace(content=[SimpleNamespace(type='text',text='bad json')]))))
    extractor=RequirementExtractor(mock)
    with pytest.raises(SourceFailure,match='AI_SCHEMA'):extractor.extract(p,detail,[],'source')
    result={'requirements':[{'key':'founder_age','operator':'LTE','value':39,'certain':True,'evidence':[
       {'source_id':'source','text':'fabricated condition','method':'LLM','confidence':1,'verified':True}]}],
       'program_types':['GRANT'],'eligibility_section_quote':'fabricated section','evidence_complete':True}
    mock.messages.create.return_value.content[0].text=json.dumps(result)
    actual=extractor.extract(p,detail,[],'source')
    assert not actual.evidence_complete and not actual.requirements[0].certain and not actual.requirements[0].evidence[0].verified
