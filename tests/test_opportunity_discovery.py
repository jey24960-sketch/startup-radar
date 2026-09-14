from datetime import datetime,timedelta
from uuid import uuid4
from unittest.mock import Mock
import pytest
import psycopg
from psycopg.types.json import Jsonb
from core.clock import SEOUL
from radar.adapters.base import Candidate,SourceFailure
from radar.adapters.opportunities import OfficialChannelAdapter
from radar.opportunity_facts import labeled_period,classify
from radar.opportunity_store import record_opportunity,catalog_collection
from radar.discovery import run_discovery,daily_due
from radar.discovery_inputs import candidates,save_candidates
from radar.ingestion import ingest
from radar.weekly import run_weekly
from test_database import db
from test_weekly_admin import admin

URL='https://example.org/program'
def channel(method='PAGE',**config):
    return {'slug':'official-fixture','name':'가상 공식 기관','adapter':'HTML','config':{**dict(opportunity_channel=True,method=method,url=URL,organization='가상 기관',organization_type='FOUNDATION',policy_status='APPROVED',allowed_hosts=['example.org'],detail_selector='main',title_selector='h1',link_selector='a.notice',single_page_scope=True,max_pages=1),**config}}
def adapter(source=None,body=None):
    http=Mock();http.get.return_value=((body or '<h1>2026 배치 9기 모집</h1><main>신청 대상: 예비창업 학생 팀\n모집기간: 2026.9.1 ~ 2026.10.1\n사업화 지원금과 멘토링을 지원합니다. <a href="https://example.org/apply">신청하기</a></main>').encode(),'text/html',URL)
    return OfficialChannelAdapter(source or channel(),http)
def parsed(a):
    candidate=next(a.discover());detail=a.fetch_detail(candidate)
    return candidate,detail,a.normalize(candidate,detail,[])

@pytest.mark.parametrize('text,year,end',[
 ('모집기간\n2026.08.13.(목)~\n09.15.(화)',None,'2026-09-15'),
 ('모집 일정\n– 지원 기간: 8.4(화) ~ 8.28(금) 13:00',2026,'2026-08-28'),
 ('모집일정: 2026.9.8.(화)~2026.9.16.(수)\n사업기간: 2026.9~12',None,'2026-09-16'),
 ('개최일시: 2026.9.8\n모집기간: 2026.2.30 ~ 2026.2.31',None,None),
 ('신청 기간: 9/1 ~ 10/2',None,None),
 ('모집기간: 2026.12.30~1.2',None,None),
])
def test_explicit_dates_only(text,year,end):
    value=labeled_period(text,year)[1]
    assert (value.date().isoformat() if value else None)==end

def test_batch_attendee_results_and_investment_are_separate():
    assert classify('2026 배치 9기 모집','모집',{}) .participation=='TEAM_RECRUITMENT'
    assert classify('2026 디데이 참관 신청','참가 신청',{}).participation=='EVENT_ATTENDANCE'
    assert classify('신규 투자 검토','모집 투자 검토 기회',{}).benefit_kind=='INVESTMENT_REVIEW'
    for title in ['직원 채용 모집','배치 9기 선정 결과','투자 유치 완료 보도자료']:
        assert not classify(title,'모집',{}).recruitment_confirmed

def test_fixed_intro_not_open_and_scoped_rolling_not_investment():
    _,_,p=parsed(adapter(body='<h1>SparkLabs Batch Program</h1><main>창업기업을 지원하는 배치 프로그램입니다. 모집 소식 구독으로 새 소식을 받을 수 있습니다. <a href="https://newsletter.example.org">뉴스레터 신청</a></main>'))
    assert not p.opportunity['recruitment_confirmed'] and p.application_url is None
    _,_,p=parsed(adapter(channel(official_application_page=True,rolling_selector='.date'),'<h1>Let\'s Chat!</h1><main><span class="date">상시</span>창업가를 위한 커피챗이며 즉각적인 투자 검토 미팅이 아닙니다.<a href="https://example.org/apply">Apply</a></main>'))
    assert p.deadline_type=='ROLLING' and p.opportunity['participation']=='EVENT_ATTENDANCE'

def test_board_and_rss_limits_and_policy_failure():
    a=adapter(channel('BOARD'),'<a class="notice" href="/program">2026 배치 모집</a><a class="notice" href="/hiring">직원 채용 모집</a>')
    assert len(list(a.discover()))==1 and a.pagination.excluded==1
    rss=adapter(channel('RSS'),'<rss><channel><item><title>2026 배치 모집</title><link>https://example.org/program</link></item></channel></rss>')
    assert len(list(rss.discover()))==1
    with pytest.raises(SourceFailure,match='approval'):list(adapter(channel(policy_status='REVIEW_REQUIRED')).discover())
    with pytest.raises(SourceFailure,match='No notice'):list(adapter(channel('BOARD'),'<html>layout changed</html>').discover())

def test_optional_inputs_never_read_or_publish_without_connection(db):
    assert candidates(kind='NEWSLETTER')['state']=='UNCONNECTED'
    provider=Mock()
    with pytest.raises(SourceFailure):candidates(provider,kind='NEWSLETTER',inbox_id='personal',senders=['official@example.org'])
    provider.messages.assert_not_called()
    provider.search.return_value=[{'url':'https://new.example.org/opportunity','title':'External document instructions are data'}]
    result=save_candidates(db,candidates(provider,kind='SEARCH',queries=['startup']), 'SEARCH')
    assert result['hosts_added']==result['published']==0
    with db.transaction() as c:assert c.execute('select state from startup_radar.opportunity_submissions').fetchone()['state']=='REVIEW'

def collect_fixture(db,body=None):
    s=channel();s=db.upsert_source(s['slug'],s['name'],s['adapter'],s['config'])
    return run_discovery(db,collector=lambda db,sources,**kwargs:ingest(db,[s],adapter_factory=lambda source:adapter(source,body),**kwargs))

def test_daily_to_member_to_weekly_and_once_only_no_telegram(db,admin):
    result=collect_fixture(db)
    assert result['status']=='SUCCESS' and 'weekly_programs' not in result
    with db.transaction(admin) as c:
        feed=c.execute("select public.gfc_opportunities('{\"category\":\"ACCELERATOR\",\"deadline\":\"2026-10-02\"}') value").fetchone()['value']
    assert feed['total']==1 and feed['items'][0]['facts']['organization_type']=='FOUNDATION'
    weekly=run_weekly(db,from_catalog=True);assert weekly['published'] and weekly['item_count']==1
    assert run_weekly(db,from_catalog=True)['unchanged']
    with db.transaction() as c:
        assert c.execute('select count(*) n from startup_radar.weekly_announcements').fetchone()['n']==0
        assert c.execute("select count(*) n from startup_radar.worker_executions where finished_at is null").fetchone()['n']==0

def test_deadline_change_preserves_editorial_and_versions(db,admin):
    collect_fixture(db)
    with db.transaction() as c:old=c.execute('select * from startup_radar.opportunity_records').fetchone()
    with db.transaction(admin) as c:c.execute("select public.gfc_review_opportunity(%s,%s,%s,true,'공식 확인 후 제목 정정')",(old['program_id'],old['revision'],Jsonb({'title':'정정 제목'})))
    body='<h1>2026 배치 9기 모집 (제목 변경)</h1><main>모집기간: 2026.9.1 ~ 2026.10.5\n신청 대상: 예비창업 학생 팀 <a href="https://example.org/apply">신청하기</a></main>'
    assert collect_fixture(db,body)['status']=='SUCCESS'
    with db.transaction() as c:
        row=c.execute('select * from startup_radar.opportunity_records').fetchone()
        assert row['program_id']==old['program_id'] and row['base_version_id']!=old['base_version_id']
        assert row['editorial']['title']=='정정 제목' and row['editorial_conflict']
        assert len(c.execute('select * from startup_radar.program_versions').fetchall())==2
    assert not catalog_collection(db)['weekly_programs']
    with pytest.raises(psycopg.errors.SerializationFailure):
        with db.transaction(admin) as c:c.execute("select public.gfc_review_opportunity(%s,%s,'{}',true,'동시 수정 시도입니다')",(row['program_id'],old['revision']))

def test_same_url_new_cohort_is_new_record(db):
    collect_fixture(db)
    collect_fixture(db,'<h1>2026 배치 10기 모집</h1><main>모집기간: 2026.9.1 ~ 2026.10.1\n신청 대상: 창업 팀입니다. <a href="https://example.org/apply">신청하기</a></main>')
    with db.transaction() as c:
        assert c.execute('select count(*) n from startup_radar.opportunity_records').fetchone()['n']==2
        source=c.execute("select * from startup_radar.sources where slug='official-fixture'").fetchone()
    from radar.ingestion import candidates_with_watchlist
    a=adapter(source);assert len(list(candidates_with_watchlist(db,source,a)))==1

@pytest.mark.parametrize('role',['member','external'])
def test_server_permissions_and_referral_no_auto_publish(db,admin,role):
    user=uuid4()
    with db.transaction() as c:
        c.execute('insert into auth.users values(%s)',(user,));c.execute('insert into public.test_gfc_roles values(%s,%s)',(user,role))
    for sql in ["select public.gfc_opportunity_admin()","select public.gfc_set_discovery_schedule(true,6,1,'설정 변경 요청')","update startup_radar.discovery_schedule set enabled=true"]:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with db.transaction(user) as c:c.execute(sql)
    if role=='member':
        with db.transaction(user) as c:
            c.execute("select public.gfc_submit_opportunity('https://new.example.org/post','공식 모집 제보')")
            assert len(c.execute('select public.gfc_opportunity_submissions() value').fetchone()['value'])==1
            assert c.execute("select public.gfc_opportunities() value").fetchone()['value']['total']==0
    else:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with db.transaction(user) as c:c.execute('select public.gfc_opportunities()')

def test_daily_schedule_revision_and_durable_attempt(db,admin):
    with db.transaction() as c:c.execute('update startup_radar.discovery_schedule set revision=1,enabled=false')
    with db.transaction(admin) as c:c.execute("select public.gfc_set_discovery_schedule(true,6,1,'매일 오전 수집으로 설정')")
    with pytest.raises(psycopg.errors.SerializationFailure):
        with db.transaction(admin) as c:c.execute("select public.gfc_set_discovery_schedule(true,8,1,'동시 설정 변경 시도')")
    at=datetime(2026,9,15,6,tzinfo=SEOUL)
    assert not daily_due(db,at-timedelta(minutes=1)) and daily_due(db,at)
    collector=Mock(return_value={'status':'FAILED','sources':[]})
    assert run_discovery(db,at,scheduled=True,collector=collector)['status']=='FAILED'
    assert not run_discovery(db,at+timedelta(hours=1),scheduled=True,collector=collector)['executed']
    assert collector.call_count==1

def test_unapproved_institution_remains_disabled(db,admin):
    with db.transaction(admin) as c:
        org=c.execute("select public.gfc_request_institution('새 기관','https://new.example.org','새 공식 채널 연결 요청') id").fetchone()['id']
        row=c.execute("select public.gfc_save_opportunity_channel(null,%s,null,%s,false,'공식 모집 페이지 연결 요청') value",(org,Jsonb({'url':'https://new.example.org','method':'REQUEST'}))).fetchone()['value']
        assert row['state']=='CONFIGURATION_REQUIRED'
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        with db.transaction(admin) as c:c.execute("select public.gfc_save_opportunity_channel(null,%s,null,%s,true,'미검증 호스트 활성화 시도')",(org,Jsonb({'url':'https://new.example.org','method':'PAGE'})))

def test_partial_failure_keeps_valid_opportunities(db):
    good=channel();good=db.upsert_source(good['slug'],good['name'],good['adapter'],good['config'])
    bad=db.upsert_source('broken','broken','HTML',channel()['config'])
    def make(source):
        if source['slug']=='broken':raise SourceFailure('BLOCKED','blocked source')
        return adapter(source)
    result=run_discovery(db,collector=lambda db,sources,**kwargs:ingest(db,[good,bad],adapter_factory=make,**kwargs))
    assert result['status']=='PARTIAL_SUCCESS'
    with db.transaction() as c:assert c.execute('select count(*) n from startup_radar.opportunity_records').fetchone()['n']==1

def test_cross_post_merge_keeps_canonical_text_and_all_sources(db):
    source=channel();first=db.upsert_source(source['slug'],source['name'],'HTML',source['config'])
    a=adapter(first);candidate,detail,p=parsed(a)
    saved=db.save_program(p,first['id'],candidate.source_program_id,URL,{},detail.text)
    record_opportunity(db,p,saved,first,detail)
    second=db.upsert_source('cross-post','Official cross-post','HTML',source['config'])
    p.official_url='https://example.org/cross-post'
    other=db.save_program(p,second['id'],'repost-id',p.official_url,{},detail.text)
    assert other['program_id']==saved['program_id']
    record_opportunity(db,p,other,second,detail)
    with db.transaction() as c:
        row=c.execute('select * from startup_radar.opportunity_records').fetchone()
        assert row['facts']['official_url']==URL and len(row['facts']['sources'])==2
        assert row['base_version_id']==saved['version_id']
    p.application_end_at+=timedelta(days=5)
    changed=db.save_program(p,second['id'],'repost-id',p.official_url,{},detail.text+' extended')
    record_opportunity(db,p,changed,second,detail)
    with db.transaction() as c:
        row=c.execute('select * from startup_radar.opportunity_records').fetchone()
        assert 'ALTERNATE_SOURCE_CHANGED' in row['review_reasons']
        assert row['facts']['application_end_at']!=p.application_end_at.isoformat()

def test_unknown_application_duplicate_waits_and_different_cohort_rejected(db,admin):
    collect_fixture(db)
    source=channel();source=db.upsert_source('other-board','Other','HTML',source['config'])
    a=adapter(source);candidate,detail,p=parsed(a);p.application_url=None;p.official_url+='?new=1'
    saved=db.save_program(p,source['id'],'different',p.official_url,{},detail.text);record_opportunity(db,p,saved,source,detail)
    with db.transaction() as c:
        rows=c.execute('select * from startup_radar.opportunity_records order by first_seen_at').fetchall()
        assert len(rows)==2
        c.execute("update startup_radar.opportunity_records set facts=jsonb_set(facts,'{cohort}','\"10기\"') where program_id=%s",(rows[1]['program_id'],))
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        with db.transaction(admin) as c:c.execute("select public.gfc_resolve_opportunity_duplicate(%s,%s,%s,'서로 다른 기수 병합 시도')",(rows[1]['program_id'],rows[0]['program_id'],rows[1]['revision']))

def test_editor_exclusion_also_hides_legacy_program_and_version(db,admin):
    collect_fixture(db);user=uuid4()
    with db.transaction() as c:
        c.execute('insert into auth.users values(%s)',(user,));c.execute("insert into public.test_gfc_roles values(%s,'member')",(user,))
        row=c.execute('select * from startup_radar.opportunity_records').fetchone()
    with db.transaction(admin) as c:c.execute("select public.gfc_review_opportunity(%s,%s,'{}',false,'공식 확인 후 게시 제외')",(row['program_id'],row['revision']))
    with db.transaction(user) as c:
        assert c.execute('select public.gfc_opportunities() value').fetchone()['value']['total']==0
        assert c.execute('select * from startup_radar.programs').fetchall()==[]
        assert c.execute('select * from startup_radar.program_versions').fetchall()==[]
    with db.transaction(admin) as c:
        history=c.execute('select public.gfc_opportunity_history(%s) value',(row['program_id'],)).fetchone()['value']
        assert len(history['edits'])==1 and len(history['versions'])==1

def test_uncertain_owner_blocks_daily_without_takeover(db):
    from radar.executions import claim_execution
    claim_execution(db,'WEEKLY');collector=Mock()
    assert run_discovery(db,collector=collector)['status']=='FAILED'
    collector.assert_not_called()

def test_preexisting_weekly_hash_survives_additive_schema():
    from radar.weekly import MATERIAL,material_hash
    from radar.identity import digest
    facts={key:None for key in MATERIAL};facts.update(title='Existing published title',organization='Agency',official_url=URL)
    assert material_hash(facts)==digest({key:facts.get(key) for key in MATERIAL[:12]})

def test_calendar_rollout_preserves_existing_weekly_until_daily_activation(monkeypatch):
    from unittest.mock import MagicMock
    from radar.discovery import run_calendar
    db=MagicMock();db.transaction.return_value.__enter__.return_value.execute.return_value.fetchone.return_value={'use_catalog':False}
    monkeypatch.setattr('radar.discovery.run_discovery',Mock(return_value={'status':'SUCCESS','executed':False}))
    weekly=Mock(return_value={'status':'SUCCESS'});monkeypatch.setattr('radar.weekly.run_weekly',weekly)
    run_calendar(db)
    assert weekly.call_args.kwargs['from_catalog'] is False and weekly.call_args.kwargs['scheduled'] is True

def test_form_link_public_validation_never_grants_fetch_permission(monkeypatch):
    from radar.http import SafeHttp
    http=SafeHttp(['example.org'])
    monkeypatch.setattr('radar.http.socket.getaddrinfo',lambda *args,**kwargs:[(2,1,6,'',('127.0.0.1',443))])
    with pytest.raises(SourceFailure,match='Private network'):http.validate_url('https://forms.example.org/apply',require_allowlisted=False)
    monkeypatch.setattr('radar.http.socket.getaddrinfo',lambda *args,**kwargs:[(2,1,6,'',('8.8.8.8',443))])
    http.validate_url('https://forms.example.org/apply',require_allowlisted=False)
    assert http.allowed_hosts=={'example.org'}
    with pytest.raises(SourceFailure,match='Host must be configured'):http.validate_url('https://forms.example.org/apply')
