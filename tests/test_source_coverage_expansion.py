"""Recall fixes preserve official dates, source scope and no-AI collection."""
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock
import pytest
from core.clock import SEOUL
from radar.adapters.weekly_direct import OfficialChannelAdapter
from radar.adapters.base import Candidate, SourceFailure
from radar.opportunity_facts import weekly_decision

ROOT=Path(__file__).resolve().parents[1]
REGISTRY=json.loads((ROOT/'weekly-direct-sources.json').read_text(encoding='utf-8'))
AT=datetime(2026,10,27,9,tzinfo=SEOUL)

def source(slug):
    return deepcopy(next(s for s in REGISTRY if s['slug']==slug))

def test_d2sf_current_application_link_is_discovered_instead_of_old_campus_page():
    s=source('weekly-naver-d2sf');adapter=OfficialChannelAdapter(s,Mock())
    adapter.read_page=Mock(return_value=(b'<a href="https://d2sf.naver.com/ko/story/5">FAQ</a>', 'text/html',s['config']['url']))
    candidates=list(adapter.discover())
    assert [x.official_detail_url for x in candidates]==['https://d2sf.naver.com/ko/story/5']
    assert all('/campus/' not in x.official_detail_url for x in candidates)

def d2sf_program(html):
    s=source('weekly-naver-d2sf');adapter=OfficialChannelAdapter(s,Mock())
    candidate=Candidate(s['slug'],'story-5',s['config']['url'],'https://d2startup.com/ko/story/5','FAQ')
    adapter.read_page=Mock(return_value=(html,'text/html',candidate.official_detail_url))
    detail=adapter.fetch_detail(candidate)
    return adapter.normalize(candidate,detail,[]),candidate

def test_d2sf_deadline_year_comes_from_official_published_date_not_clock():
    html=(ROOT/'tests/fixtures/d2sf_2026_autumn_notice.html').read_bytes()
    program,candidate=d2sf_program(html)
    assert program.application_start_at is None
    assert program.application_end_at==datetime(2026,11,8,23,59,59,tzinfo=SEOUL)
    assert program.application_end_precision=='DATE'
    assert candidate.raw_metadata['source_published_at']=='2026-09-11T00:00:00+09:00'
    assert weekly_decision(program,candidate.raw_metadata['weekly_direct_facts'],AT)[0]=='ACCEPTED'
    # Removing the publisher's year must not be repaired with the machine clock.
    program,_=d2sf_program(html.replace(b'September 11, 2026',b'Publication date unavailable'))
    assert program.application_end_at is None

def test_d2sf_cross_year_deadline_is_not_guessed():
    html=(ROOT/'tests/fixtures/d2sf_2026_autumn_notice.html').read_text(encoding='utf-8')
    html=html.replace('September 11, 2026','December 11, 2026').replace('~11월 8일','~1월 8일')
    program,_=d2sf_program(html.encode())
    assert program.application_end_at is None

def test_page_links_are_followed_sequentially_and_pinned_notice_is_deduplicated():
    s=source('weekly-unist-venture-notices')
    s['config'].update(max_pages=3,max_records=50)
    adapter=OfficialChannelAdapter(s,Mock())
    first=s['config']['url']
    second=first+'?mode=list&article.offset=10&articleLimit=10'
    page1=b'<div class="b-title-box"><a href="?mode=view&articleNo=1&article.offset=0">startup 1</a></div><a href="?mode=list&article.offset=10&articleLimit=10">2</a><a href="?mode=list&article.offset=20">3</a>'
    page2=b'<div class="b-title-box"><a href="?mode=view&articleNo=1&article.offset=10">startup 1</a><a href="?mode=view&articleNo=2&article.offset=10">startup 2</a></div>'
    adapter.read_page=Mock(side_effect=[(page1,'text/html',first),(page2,'text/html',second)])
    rows=list(adapter.discover())
    assert len(rows)==2
    assert adapter.read_page.call_args_list[1].args[0]==second
    assert adapter.pagination.report()['pagination_complete'] is True
    assert adapter.pagination.report()['pages_requested']==2

def test_page_budget_and_record_budget_are_not_reported_as_complete():
    s=source('weekly-unist-venture-notices');s['config']['max_pages']=1
    adapter=OfficialChannelAdapter(s,Mock())
    adapter.read_page=Mock(return_value=(b'<div class="b-title-box"><a href="?mode=view&articleNo=1">notice</a></div><a href="?mode=list&article.offset=10">2</a>','text/html',s['config']['url']))
    with pytest.raises(SourceFailure,match='PAGE_LIMIT'):list(adapter.discover())
    assert adapter.pagination.report()['pagination_complete'] is False

def test_unrelated_pagination_host_and_path_are_not_followed():
    s=source('weekly-unist-venture-notices');adapter=OfficialChannelAdapter(s,Mock())
    soup=adapter.soup(b'<a href="https://other.example/list?article.offset=10">2</a><a href="/other?article.offset=10">2</a>')
    assert adapter.next_listing(soup,s['config']['url']) is None

def test_bizinfo_nested_html_documents_keep_the_public_notice_body():
    s=source('weekly-bizinfo-events');adapter=OfficialChannelAdapter(s,Mock())
    # The official portal currently emits nested full documents. lxml drops the
    # later body, while the explicitly selected stdlib parser preserves it.
    html=b'<html><body><header>menu</header></body></html><html><body><div class="support_project_detail"><h2 class="title">2026 startup recruitment</h2><p>Application period and official programme details.</p></div></body></html>'
    assert adapter.soup(html).select_one('.support_project_detail h2.title').get_text()=='2026 startup recruitment'

def test_verified_new_sources_and_pagination_scopes_are_registered():
    slugs={'weekly-naver-d2sf','weekly-unist-venture-notices','weekly-korea-anam-programs','weekly-bizinfo-events'}
    assert slugs <= {s['slug'] for s in REGISTRY if s['enabled']}
    for slug in slugs:
        s=source(slug)
        assert s['config']['policy_status']=='APPROVED'
        assert s['config']['weekly_direct'] is True
    for slug in ('weekly-unist-venture-notices','weekly-bizinfo-events','weekly-postech-aif-notices'):
        assert source(slug)['config']['max_pages']>1

def test_conflicting_korea_header_and_body_deadlines_cannot_pass_seven_day_gate():
    from radar.actionability import actionability
    s=source('weekly-korea-anam-programs');adapter=OfficialChannelAdapter(s,Mock())
    html='''<div class="proView"><span class="detailTitle">AI 제조창업 지원 프로그램</span>
      <div class="postPeriod"><span class="addDay">등록일: 2026.10.13</span>
      <span class="addDay">신청기간: 2026.10.13 ~ 2026.11.06</span></div>
      <p>예비 제조창업자 및 초기 기업 모집, 시제품 설계 지원</p>
      <p>신청기간: 10월 23일 금요일 오후 5시까지</p>
      <p>지원기간: 11월 30일까지</p></div>'''
    candidate=Candidate(s['slug'],'1154',s['config']['url'],'https://kustartup.korea.ac.kr/program/programView.do?seq=1154','AI 창업지원')
    adapter.read_page=Mock(return_value=(html.encode(),'text/html',candidate.official_detail_url))
    detail=adapter.fetch_detail(candidate);program=adapter.normalize(candidate,detail,[])
    assert program.application_end_at is None
    assert candidate.raw_metadata['application_period_conflict'] is True
    facts=candidate.raw_metadata['weekly_direct_facts']
    assert 'APPLICATION_PERIOD_CONFLICT' in facts['review_reasons']
    assert len(facts['evidence']['application_period_conflict']['declarations'])==2
    assert weekly_decision(program,facts,AT)[0]=='REVIEW'
    assert actionability(program.model_dump(mode='json'),AT)==(False,'DEADLINE_UNKNOWN')
