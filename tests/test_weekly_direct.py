import json
import os
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock
import pytest
from core.clock import SEOUL
from radar.adapters.base import Candidate, AcquiredDetail, SourceFailure
from radar.adapters.weekly_direct import OfficialChannelAdapter
from radar.opportunity_facts import labeled_period, weekly_decision
from radar.ingestion import build_adapter, ingest
from radar.weekly_scope import weekly_sources, collection_completed
from radar.weekly import build_briefing, run_weekly, snapshot
from radar.models import Program
from test_database import db
from test_weekly import collection
from test_weekly_scope import capped_source

ROOT=Path(__file__).resolve().parents[1]
SOURCES=json.loads((ROOT/'weekly-direct-sources.json').read_text(encoding='utf-8'))
SAMPLES=json.loads((ROOT/'tests/fixtures/weekly_direct_samples.json').read_text(encoding='utf-8'))
AT=datetime(2026,9,15,15,tzinfo=SEOUL)
DB=pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Explicit test database required')


@pytest.fixture(autouse=True)
def stable_clock(monkeypatch):
    monkeypatch.setattr('radar.dates.now',lambda:AT)
    monkeypatch.setattr('radar.adapters.weekly_direct.now',lambda:AT)


@pytest.mark.parametrize('sample',SAMPLES,ids=lambda s:s['slug'])
def test_one_real_official_sample_per_channel(sample):
    source=next(s for s in SOURCES if s['slug']==sample['slug'])
    adapter=OfficialChannelAdapter(source,Mock())
    candidate=Candidate(**deepcopy(sample['candidate']))
    program=adapter.normalize(candidate,AcquiredDetail(**deepcopy(sample['detail'])),[])
    assert program.title==sample['detail']['title']
    assert program.organization==source['config']['organization']
    assert program.official_url.startswith('https://')
    decision,reason=weekly_decision(program,candidate.raw_metadata['weekly_direct_facts'],AT)
    if source['slug'] in ('weekly-orange-farm','weekly-antler-residency','weekly-yonsei-notices'):
        assert decision=='ACCEPTED'
    else:
        assert decision in ('REVIEW','EXCLUDED')
    if source['slug']=='weekly-yonsei-notices':
        assert program.application_end_at==datetime(2026,11,30,23,59,59,tzinfo=SEOUL)
    if source['slug']=='weekly-lotte-recruitment':
        assert reason=='CLOSED'


def test_direct_config_is_explicit_bounded_html_and_kept_separate_from_api_scope():
    assert len(SOURCES)==8 and all(s['enabled'] for s in SOURCES)
    before=deepcopy(SOURCES)
    assert weekly_sources(SOURCES)==before and SOURCES==before
    assert all(s['config']['max_pages']==1 and s['config']['method'] in ('PAGE','BOARD') for s in SOURCES)
    assert all(isinstance(build_adapter(s),OfficialChannelAdapter) for s in SOURCES)
    success={'status':'SUCCESS','failures':[],'coverage':{'pagination_complete':True}}
    assert collection_completed([capped_source(),capped_source()]+[success]*8)
    assert not collection_completed([capped_source(),capped_source(),{'status':'FAILED'}])


@pytest.mark.parametrize('text,year,expected',[
    ('신청 기간: 2026.9.1 ~ 9.30',None,30),
    ('모집 기간: 해당연도 03.01 ~ 11.30',2026,30),
    ('모집 기간: 해당연도 03.01 ~ 11.30',None,None),
    ('행사 일시: 2026.9.30 14:00',2026,None),
    ('모집 기간: 9.1 ~ 9.30',None,None),
    ('모집 기간: 2026.9.30 ~ 9.1',None,None),
])
def test_only_evidenced_application_periods(text,year,expected):
    start,end,sp,ep,evidence=labeled_period(text,year)
    assert (end.day if end else None)==expected


@pytest.mark.parametrize('title,text',[
    ('2026 창업팀 모집','사업 소개만 있고 접수 기간 없음'),
    ('2026 창업팀 모집 결과 발표','상시 모집'),
    ('2026 창업팀 모집','현재 모집 기간이 아닙니다. 상시 모집'),
    ('2026 창업팀 모집','프로그램 진행 시 상시 모집'),
    ('2026 창업팀 모집','모집 기간: 2026.1.1 ~ 2026.2.1'),
])
def test_undated_results_closed_and_conditional_pages_never_auto_publish(title,text):
    source={**SOURCES[0],'config':{**SOURCES[0]['config'],'method':'PAGE'}}
    candidate=Candidate(source['slug'],'id','https://example.org','https://example.org',title)
    adapter=OfficialChannelAdapter(source,Mock())
    program=adapter.normalize(candidate,AcquiredDetail(candidate.official_detail_url,text,title),[])
    assert weekly_decision(program,candidate.raw_metadata['weekly_direct_facts'],AT)[0]!='ACCEPTED'


def test_pagination_query_changes_do_not_change_notice_identity():
    sample=deepcopy(next(s for s in SAMPLES if s['slug']=='weekly-postech-aif-notices'))
    source=next(s for s in SOURCES if s['slug']==sample['slug'])
    adapter=OfficialChannelAdapter(source,Mock())
    ids=[]
    for offset in (0,10):
        candidate=Candidate(**sample['candidate'])
        detail=AcquiredDetail(**sample['detail'])
        detail.url=detail.url.replace('article.offset=0',f'article.offset={offset}')
        program=adapter.normalize(candidate,detail,[])
        ids.append(candidate.source_program_id)
        assert 'article.offset' not in program.official_url
    assert ids[0]==ids[1]


def test_declared_record_cap_is_honest_scope_not_a_fake_failure():
    config={**SOURCES[0]['config'],'url':'https://example.org/list','link_selector':'a',
        'required_title_pattern':'recruit','max_records':1,'max_pages':1,'method':'BOARD'}
    adapter=OfficialChannelAdapter({'slug':'fixture','name':'Fixture','config':config},Mock())
    adapter.read_page=Mock(return_value=(b'<a href="/1">recruit 1</a><a href="/2">recruit 2</a>',
        'text/html','https://example.org/list'))
    assert len(list(adapter.discover()))==1
    report=adapter.pagination.report()
    assert report['pagination_complete'] and report['record_cap_reached']
    assert report['scope']=='CONFIGURED_CHANNEL'
    adapter.read_page=Mock(side_effect=SourceFailure('NETWORK','Real failure'))
    with pytest.raises(SourceFailure,match='NETWORK'):list(adapter.discover())


def test_application_link_validation_never_grants_fetch_permission(monkeypatch):
    from radar.http import SafeHttp
    monkeypatch.setattr('radar.http.socket.getaddrinfo',lambda *args,**kwargs:
        [(2,1,6,'',('93.184.216.34',443))])
    client=SafeHttp(['official.example'])
    client.validate_url('https://forms.example/apply',require_allowlisted=False)
    with pytest.raises(SourceFailure,match='UNAPPROVED_HOST'):
        client.get('https://forms.example/apply')
    monkeypatch.setattr('radar.http.socket.getaddrinfo',lambda *args,**kwargs:
        [(2,1,6,'',('127.0.0.1',443))])
    with pytest.raises(SourceFailure,match='UNSAFE_ADDRESS'):
        client.validate_url('https://forms.example/apply',require_allowlisted=False)


@DB
def test_real_samples_enter_existing_storage_and_one_weekly_post(db,monkeypatch):
    monkeypatch.setattr('radar.ingestion.RequirementExtractor',Mock(side_effect=AssertionError('No AI')))
    sources=[db.upsert_source(s['slug'],s['name'],s['adapter'],s['config']) for s in SOURCES]
    def factory(source):
        sample=next(s for s in SAMPLES if s['slug']==source['slug'])
        adapter=OfficialChannelAdapter(source,Mock())
        candidate=Candidate(**deepcopy(sample['candidate']))
        adapter.discover=lambda:iter([candidate])
        adapter.fetch_detail=lambda _:AcquiredDetail(**deepcopy(sample['detail']))
        adapter.fetch_documents=Mock(side_effect=AssertionError('No OCR'))
        adapter.pagination.complete=True
        return adapter
    acquired=ingest(db,sources,adapter_factory=factory,structured_only=True)
    assert acquired['status']=='SUCCESS' and len(acquired['weekly_programs'])==3
    assert sum(s['parsed'] for s in acquired['sources'])==8
    assert sum(s['coverage']['accepted_records'] for s in acquired['sources'])==3
    assert sum(s['coverage']['review_records']+s['coverage']['excluded_records'] for s in acquired['sources'])==5
    first=build_briefing(db,acquired,AT)
    second=build_briefing(db,acquired,AT)
    assert first['item_count']==3 and second['briefing_id']==first['briefing_id']
    with db.transaction() as c:
        assert c.execute('select count(*) n from startup_radar.programs').fetchone()['n']==8
        assert c.execute('select count(*) n from startup_radar.program_sources').fetchone()['n']==8
        assert c.execute('select count(*) n from startup_radar.program_versions').fetchone()['n']==8
        assert c.execute('select count(*) n from startup_radar.weekly_briefings').fetchone()['n']==1


@DB
def test_exact_cross_source_period_dedup_preserves_provenance_not_fuzzy(db):
    api=db.upsert_source('test-api','API','BIZINFO',{})
    direct=db.upsert_source('test-direct','Direct','HTML',{'weekly_direct':True})
    p=Program(title='2026 Founder Program',organization='Official Org',official_url='https://api.example/1',
        application_start_at=datetime(2026,9,1,tzinfo=SEOUL),
        application_end_at=datetime(2026,9,30,tzinfo=SEOUL),deadline_type='FIXED_DATE')
    first=db.save_program(p,api['id'],'api-1',p.official_url,{},'api')
    p.official_url='https://official.example/notice/one'
    second=db.save_program(p,direct['id'],'direct-1',p.official_url,{'weekly_direct_facts':{'year':2026}},'direct')
    assert first['program_id']==second['program_id']
    acquired=collection(db,0)
    acquired['weekly_programs']=[{**saved,'snapshot':snapshot(p,{}),'status':'OPEN'} for saved in (first,second)]
    assert build_briefing(db,acquired,AT)['item_count']==1
    p.title+=' another track'
    third=db.save_program(p,direct['id'],'direct-2',p.official_url,{'weekly_direct_facts':{'year':2026}},'other')
    assert third['program_id']!=first['program_id']
    with db.transaction() as c:
        assert c.execute('select count(*) n from startup_radar.program_sources where program_id=%s',
            (first['program_id'],)).fetchone()['n']==2


@DB
def test_ambiguous_exact_identity_stays_in_review_on_rerun(db):
    sources=[db.upsert_source(str(i),str(i),'HTML',{'weekly_direct':True} if i==2 else {}) for i in range(3)]
    p=Program(title='Exact title',organization='Official Org',official_url='https://example.org/a',
        application_start_at=datetime(2026,9,1,tzinfo=SEOUL),
        application_end_at=datetime(2026,9,30,tzinfo=SEOUL),deadline_type='FIXED_DATE')
    for i in range(2):
        p.official_url=f'https://example.org/{i}'
        db.save_program(p,sources[i]['id'],str(i),p.official_url,{},str(i))
    p.official_url='https://example.org/direct'
    first=db.save_program(p,sources[2]['id'],'direct',p.official_url,{'weekly_direct_facts':{'year':2026}},'direct')
    second=db.save_program(p,sources[2]['id'],'direct',p.official_url,{'weekly_direct_facts':{'year':2026}},'direct')
    assert first['duplicate_conflict'] and second['duplicate_conflict']
    assert first['program_id']==second['program_id']


@DB
def test_failed_direct_source_preserves_valid_article_and_honest_partial(db):
    acquired=collection(db)
    acquired['sources'].append({'status':'FAILED','parsed':0,'failures':[{'kind':'NETWORK'}]})
    result=build_briefing(db,acquired,AT)
    assert result['published'] and result['item_count']==3 and result['status']=='PARTIAL_SUCCESS'


@DB
def test_source_health_check_never_sends_to_existing_subscribers(db,monkeypatch):
    acquired=collection(db)
    db.upsert_source('weekly-b','B','BIZINFO',{})
    first=build_briefing(db,acquired,AT)
    announcement=Mock(return_value={'state':'DELIVERY_DISABLED'})
    monkeypatch.setattr('radar.weekly.announce',announcement)
    transport=Mock()
    result=run_weekly(db,transport,at=AT,collector=Mock(return_value=acquired),check_sources=True)
    assert result['briefing_id']==first['briefing_id'] and result['unchanged']
    assert announcement.call_args.args[2] is None and not transport.send.called
