import json
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4
import pytest
from psycopg.types.json import Jsonb
from radar.adapters.base import Candidate,SourceFailure
from radar.adapters.opportunities import OfficialChannelAdapter
from radar.opportunity_facts import explicit_date,labeled_period
from radar.opportunity_facts import classify
from radar.institutions import seed_institutions
from test_opportunity_discovery import adapter,channel,parsed
from test_database import db
from test_weekly_admin import admin

@pytest.mark.parametrize('value,year,end',[
 ("모집 기간 : '26.02.23(월) ~ 03.31(화) 까지",2026,'2026-03-31T23:59:59+09:00'),
 ("모집 기간 : '25.02.14.(금) ~ 03.16.(일) 24:00 까지",2025,'2025-03-17T00:00:00+09:00'),
 ("모집 기간 : '25.02.14 ~ 03.16",2026,None),
 ('신청기간: ~2026. 9. 17.(목)까지',None,'2026-09-17T23:59:59+09:00'),
 ('모집은 2026년 12월 1일 ~ 2026년 12월 31일에 예정돼 있습니다.',None,'2026-12-31T23:59:59+09:00'),
 ('접수 기간은 6월 15일부터 26일까지이며',2026,'2026-06-26T23:59:59+09:00'),
 ('접수 기간은 6월 15일부터 26일까지이며',None,None),
 ('모집기간: 2026.9.1 ~ 2026.9.11(금) 오전 11시',None,'2026-09-11T11:00:00+09:00'),
 ('모집기간: 2026.9.1 ~ 2026.9.11(금) 오후 5시 30분',None,'2026-09-11T17:30:00+09:00'),
])
def test_explicit_deadline_variants(value,year,end):
    actual=labeled_period(value,year)[1]
    assert (actual.isoformat() if actual else None)==end

def test_invalid_clock_does_not_turn_into_open_deadline():
    assert explicit_date('2026.9.1 24:30')[0] is None
    assert explicit_date('2026.9.11(금) 오전 11:00')[0].hour==11
    assert not classify('Maker 3D프린터 경진대회 시상 결과 안내','모집한 팀의 수상 결과',{}).recruitment_confirmed

def test_board_title_excludes_badges_and_empty_duplicate():
    a=adapter(channel('BOARD',list_title_selector='.title',required_title_pattern='모집'),'<a class="notice" href="/program"><img></a><a class="notice" href="/program"><span class="title">2026 배치 모집</span><p>보도자료 선정 결과는 추후 안내</p></a>')
    found=list(a.discover());assert len(found)==1 and found[0].title=='2026 배치 모집'

def test_hanyang_get_uses_exact_content_not_next_notice():
    url='https://startup.hanyang.ac.kr/board/notice/view/4358'
    source=channel('BOARD',detail_api='HANYANG_PUBLIC_BOARD',url='https://startup.hanyang.ac.kr/')
    http=Mock();http.get.return_value=(json.dumps({'response':'success','data':{'content':{'contentId':4358,'boardEnName':'notice','title':'2026 창업동아리 모집','content':'<p>신청기간: ~2026.9.17까지</p><p>대학생 창업팀의 사업화를 위한 지원금과 멘토링 프로그램입니다.</p>'},'next':{'title':'비공개 조달','content':'DO NOT READ'}}}).encode(),'application/json',url)
    a=OfficialChannelAdapter(source,http);c=Candidate('x','4358',url,url,'');d=a.fetch_detail(c)
    assert d.title=='2026 창업동아리 모집' and 'DO NOT READ' not in d.text
    http.get.assert_called_once_with('https://startup.hanyang.ac.kr/api/board/content/4358')
    assert d.raw_metadata['official_api_url']
    http.get.return_value=(b'{"response":"success","data":{"content":{"contentId":9,"boardEnName":"notice"}}}','application/json',url)
    with pytest.raises(SourceFailure,match='requested notice'):a.fetch_detail(c)

def test_fixed_tracks_and_conditional_rolling_are_separate():
    body='<div class="heading">배치 30기 / 크리에이터 이코노미 파운더 3기 모집은</div><div class="period">2026년 12월 1일 ~ 2026년 12월 31일에 예정돼 있습니다.</div>'
    ids=[]
    for pattern in [r'배치\s*\d+기',r'크리에이터 이코노미 파운더\s*\d+기']:
        c,_,p=parsed(adapter(channel(detail_selectors=['.heading','.period'],title_selector='.heading',title_extract_pattern=pattern,title_prefix='프라이머 '),body));ids.append(c.source_program_id)
        assert p.application_start_at.month==12 and p.opportunity['recruitment_confirmed']
    assert len(set(ids))==2
    _,_,p=parsed(adapter(body='<h1>오렌지파크 소개</h1><main>창업자를 위한 커뮤니티를 지원합니다. 모집기간: 프로그램 진행 시 상시 모집. 별도 프로그램 일정을 확인하세요.</main>'))
    assert not p.opportunity['recruitment_confirmed'] and p.deadline_type=='UNKNOWN'

def test_email_application_is_evidence_not_a_sent_message_or_rolling_claim():
    _,d,p=parsed(adapter(channel(detail_selector='.pitch',email_application_selector='a',title='소풍 투자 검토 접수'),'<div class="pitch"><a href="mailto:info@example.org">투자 검토 지원하기</a></div>'))
    assert p.opportunity['recruitment_confirmed'] and p.application_url is None and p.deadline_type=='UNKNOWN'
    assert 'mailto:info@example.org' in d.raw_metadata['email_application_evidence']['text']

def test_browser_fixed_page_budget_and_no_intro_publication():
    a=adapter(channel('BROWSER',discovery_mode='PAGE',detail_ready_selector='main'))
    a.browser._render=Mock(return_value=(b'<h1>Program</h1><main>A long description of our founder community and support.</main>','text/html','https://example.org/program'))
    _,_,p=parsed(a);assert not p.opportunity['recruitment_confirmed']
    a.requests=60
    with pytest.raises(SourceFailure,match='budget'):a.read_page('https://example.org/program')

def test_browser_routes_cannot_submit_forms_or_fetch_unapproved_resources(monkeypatch):
    import sys,types
    from radar.adapters.longtail import BrowserAdapter
    class BrowserError(Exception):pass
    class BrowserTimeout(BrowserError):pass
    context=Mock();page=Mock();browser=Mock();browser.new_context.return_value=context;context.new_page.return_value=page
    runtime=Mock();runtime.chromium.launch.return_value=browser
    cm=Mock();cm.__enter__=Mock(return_value=runtime);cm.__exit__=Mock(return_value=False)
    module=types.ModuleType('playwright.sync_api');module.sync_playwright=lambda:cm;module.Error=BrowserError;module.TimeoutError=BrowserTimeout
    monkeypatch.setitem(sys.modules,'playwright',types.ModuleType('playwright'));monkeypatch.setitem(sys.modules,'playwright.sync_api',module)
    routes=[]
    def goto(*args,**kwargs):
        handler=context.route.call_args.args[1]
        for method,kind,url in [('GET','document','https://example.org/page'),('POST','xhr','https://example.org/submit'),('GET','fetch','https://private.example/secret'),('GET','image','https://example.org/poster')]:
            route=Mock();route.request.method=method;route.request.resource_type=kind;route.request.url=url;handler(route);routes.append(route)
        return types.SimpleNamespace(status=200)
    page.goto.side_effect=goto;page.content.return_value='<main>Verified public content</main>';page.url='https://example.org/page'
    http=Mock()
    def validate(url):
        if 'private.example' in url:raise SourceFailure('UNAPPROVED_HOST','Not approved')
    http.validate_url.side_effect=validate;http.get.return_value=(b'<main>Verified public content</main>','text/html','https://example.org/page')
    renderer=BrowserAdapter({'config':{'ready_selector':'main'}},http);renderer._render('https://example.org/page')
    http.get.assert_called_once_with('https://example.org/page')
    assert routes[0].fulfill.called and all(r.abort.called for r in routes[1:])
    assert context.route_web_socket.called and browser.close.called

def test_past_undated_notice_stays_unknown_but_awaits_weekly_review():
    _,_,p=parsed(adapter(channel(official_application_page=True),'<h1>2025 배치 모집</h1><main>스타트업을 모집하는 프로그램입니다. 공식 신청 링크에서 안내사항을 확인하고 지원하세요.<a href="https://example.org/apply">신청하기</a></main>'))
    assert p.deadline_type=='UNKNOWN' and 'PAST_NOTICE_DEADLINE_UNKNOWN' in p.opportunity['review_reasons']

def test_past_undated_notice_is_stored_but_not_reintroduced_in_weekly(db):
    from radar.ingestion import ingest
    from radar.opportunity_store import catalog_collection
    src=db.upsert_source(str(uuid4()),'Past official program','HTML',channel(official_application_page=True)['config'])
    a=adapter(src,'<h1>2025 배치 모집</h1><main>스타트업을 모집하는 프로그램입니다. 공식 신청 링크에서 안내사항을 확인하고 지원하세요.<a href="https://example.org/apply">신청하기</a></main>')
    result=ingest(db,[src],trigger='daily-discovery',structured_only=True,adapter_factory=lambda _:a)
    assert result['status']=='SUCCESS' and catalog_collection(db)['weekly_programs']==[]
    with db.transaction() as c:assert c.execute('select count(*) n from startup_radar.opportunity_records where confirmed').fetchone()['n']==1

def test_seed_review_opt_in_preserves_operator_edits_and_activation(db,tmp_path):
    with db.transaction() as c:c.execute('truncate startup_radar.institutions cascade')
    old={'slug':'test-expansion','name':'Fixture','kind':'UNIVERSITY','homepage':'https://example.org','approved_hosts':[],'policy_status':'REVIEW_REQUIRED','note':'previous review','channels':[]}
    path=tmp_path/'catalog.json'
    def write(org):path.write_text(json.dumps({'checked_at':'2026-09-15T00:00:00+09:00','institutions':[org]}),encoding='utf8')
    write(old);seed_institutions(db,path)
    new={**old,'approved_hosts':['example.org'],'policy_status':'APPROVED','note':'public GET checked','previous_review':{k:old[k] for k in ('approved_hosts','policy_status','note')},'channels':[{'slug':'test-expansion-channel','name':'Fixture','config':{'method':'PAGE','url':'https://example.org/program'}}]}
    write(new);seed_institutions(db,path)
    with db.transaction() as c:
        assert c.execute("select policy_status from startup_radar.institutions where slug='test-expansion'").fetchone()['policy_status']=='REVIEW_REQUIRED'
    r=seed_institutions(db,path,update_reviewed=True);assert r['reviews_updated']==['test-expansion']
    with db.transaction() as c:
        row=c.execute("select * from startup_radar.sources where slug='test-expansion-channel'").fetchone()
        assert not row['enabled'] and row['config']['policy_status']=='APPROVED'
        c.execute("update startup_radar.institutions set policy_status='REVIEW_REQUIRED',policy_note='operator investigation' where slug='test-expansion'")
    assert seed_institutions(db,path,update_reviewed=True)['review_conflicts']==['test-expansion']

def test_admin_can_enable_reviewed_browser_but_members_and_new_hosts_cannot(db,admin):
    uid=admin
    cfg={'method':'BROWSER','url':'https://example.org/program','max_pages':1,'max_records':2,'detail_selector':'main'}
    with db.transaction() as c:
        org=c.execute("insert into startup_radar.institutions(slug,name,kind,homepage,approved_hosts,policy_status) values(%s,'Browser','AC','https://example.org',array['example.org'],'APPROVED') returning id",(str(uuid4()),)).fetchone()['id']
        source=c.execute("insert into startup_radar.sources(slug,name,adapter,config,enabled) values(%s,'Browser','HTML',%s,false) returning id",(str(uuid4()),Jsonb({**cfg,'opportunity_channel':True,'ready_selector':'main','discovery_mode':'PAGE'}))).fetchone()['id']
        c.execute('insert into startup_radar.source_channels(source_id,institution_id) values(%s,%s)',(source,org))
    with db.transaction(uid) as c:
        result=c.execute('select public.gfc_save_opportunity_channel(%s,%s,1,%s,true,%s) value',(source,org,Jsonb(cfg),'Reviewed public browser source')).fetchone()['value'];assert result['id']
    with pytest.raises(Exception):
        with db.transaction(uid) as c:c.execute('select public.gfc_save_opportunity_channel(null,%s,null,%s,true,%s)',(org,Jsonb({**cfg,'url':'https://new.example.org/program'}),'Unverified new domain'))
    with pytest.raises(Exception):
        with db.transaction() as c:
            c.execute('set local role anon');c.execute('select public.gfc_save_opportunity_channel(null,%s,null,%s,true,%s)',(org,Jsonb(cfg),'Anonymous attempt'))
