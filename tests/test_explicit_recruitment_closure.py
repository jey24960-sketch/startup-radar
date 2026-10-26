"""An official closed status overrides a future formal application end date."""
from copy import deepcopy
from datetime import datetime
from unittest.mock import Mock
from types import SimpleNamespace
from contextlib import nullcontext
from uuid import uuid4

import pytest
from core.clock import SEOUL
from radar.adapters.base import Candidate,AcquiredDetail
from radar.adapters.weekly_direct import OfficialChannelAdapter
from radar.models import Program
from radar.opportunity_facts import classify,explicit_closure,weekly_decision
from radar.weekly import stored_candidates
from radar.ingestion import ingest

AT=datetime(2026,10,27,10,tzinfo=SEOUL)
URL='https://venture.yonsei.ac.kr/community/notice/199'
TITLE='[마감]☆2026 학생창업 법인설립·사업장 주소지 제공 프로그램(~11.30 모집)☆'
BODY='''법인설립 지원 및 사업장 주소지 제공
온라인 접수 바로가기 https://forms.gle/fixture ★마감되었습니다★
참여 조건: 대표가 연세대학교 재학생으로 구성된 신규 창업자 기업
모집 기간: 해당연도 03.01 ~ 11.30 (예산 소진 시 종료)
법인 설립 비용 및 법률 멘토링 비용 전액 지원
'''


def normalized(title=TITLE,text=BODY,rolling=False):
    source={'slug':'weekly-yonsei-notices','name':'연세대학교 창업지원단','adapter':'HTML','config':{
        'organization':'연세대학교 창업지원단','organization_type':'UNIVERSITY',
        'method':'BOARD','policy_status':'APPROVED','weekly_direct':True,
    }}
    candidate=Candidate(source['slug'],'fixture',URL,URL,title)
    metadata={'official_application_links':[{'url':'https://forms.gle/fixture','text':'온라인 접수','linked_from':URL}]}
    if rolling:metadata['rolling_marker']='상시'
    detail=AcquiredDetail(URL,text,title,raw_metadata=metadata)
    program=OfficialChannelAdapter(source,Mock()).normalize(candidate,detail,[])
    return source,candidate,program


def test_actual_yonsei_closed_source_keeps_dates_but_is_not_accepted():
    _,candidate,program=normalized()
    facts=candidate.raw_metadata['weekly_direct_facts']
    assert program.application_end_at==datetime(2026,11,30,23,59,59,tzinfo=SEOUL)
    assert facts['recruitment_closed'] and not facts['recruitment_confirmed']
    assert facts['evidence']['closure']=={'text':'[마감]','url':URL}
    assert weekly_decision(program,facts,AT)==('EXCLUDED','CLOSED_SOURCE_STATUS')


def test_body_closure_still_wins_when_title_badge_is_missing():
    _,candidate,program=normalized(title=TITLE.replace('[마감]',''))
    facts=candidate.raw_metadata['weekly_direct_facts']
    assert facts['evidence']['closure']=={'text':'마감되었습니다','url':URL}
    assert weekly_decision(program,facts,AT)==('EXCLUDED','CLOSED_SOURCE_STATUS')


def test_explicit_closed_status_cannot_be_turned_into_rolling_open_recruitment():
    _,candidate,program=normalized(text=BODY+'\n상시 모집\n',rolling=True)
    assert program.deadline_type=='FIXED_DATE'
    assert weekly_decision(program,candidate.raw_metadata['weekly_direct_facts'],AT)==('EXCLUDED','CLOSED_SOURCE_STATUS')


@pytest.mark.parametrize('title',[
    '[마감] 2026 예비창업자 모집','[모집 마감] 2026 예비창업자 모집',
    '[접수종료] 예비창업자 모집','【신청 종료】 창업지원사업',
])
def test_explicit_closed_title_markers_are_statuses(title):
    assert explicit_closure(title)


@pytest.mark.parametrize('text',[
    '★마감되었습니다★','접수가 마감되었습니다.','모집이 종료되었습니다.',
    '신청이 이미 마감됐습니다.','지원 마감하였습니다.',
])
def test_completed_application_closure_is_evidenced(text):
    decision=classify('2026 예비창업자 모집',text,{'official_url':URL})
    assert decision.recruitment_closed and decision.evidence['closure']['url']==URL


@pytest.mark.parametrize('text',[
    '마감 전까지 신청해 주세요.','마감 예정일은 2026.11.30입니다.',
    '마감 임박, 신청해 주세요.','정원 초과 시 조기 마감될 수 있습니다.',
    '예산 소진 시 종료합니다.','신청 마감: 2026.11.30',
    '접수가 마감되지 않았습니다.','모집은 종료되지 않았습니다.',
    '지급이 종료되었습니다. 신청은 11월 30일까지 가능합니다.',
    '지난해 모집이 종료되었습니다. 올해 신규 모집은 계속 진행합니다.',
    '이전 모집은 마감되었습니다. 이번 모집은 접수 중입니다.',
])
def test_deadline_condition_negative_and_historical_statements_are_not_closed_status(text):
    assert explicit_closure('2026 창업팀 모집',text) is None
    assert not classify('2026 창업팀 모집',text,{'official_url':URL}).recruitment_closed


def test_legacy_stored_title_is_rechecked_without_fabricating_an_end_date():
    program=Program(title=TITLE,organization='연세대학교',official_url=URL,
        application_start_at=datetime(2026,3,1,tzinfo=SEOUL),
        application_end_at=datetime(2026,11,30,tzinfo=SEOUL),deadline_type='FIXED_DATE')
    old={'recruitment_confirmed':True,'participation':'TEAM_RECRUITMENT'}
    assert weekly_decision(program,old,AT)==('EXCLUDED','CLOSED_SOURCE_STATUS')
    source,candidate,new=normalized()
    row={'program_id':'fixture-pid','version_id':'fixture-version',
        'observation_version_id':'fixture-version','normalized':new.model_dump(mode='json'),
        'source_adapter':'HTML','source_config':source['config'],
        'extraction_metadata':{'provider':'official_html_weekly'},
        'raw_metadata':{**deepcopy(candidate.raw_metadata),'weekly_decision':'ACCEPTED'},
        'last_seen_at':AT}
    # The old ACCEPTED flag does not override the latest explicit source fact.
    assert stored_candidates([row],AT)==[]


def test_closed_direct_source_removes_a_same_program_api_fallback_from_this_collection():
    source,candidate,program=normalized()
    source['id']=uuid4()
    api={'id':uuid4(),'slug':'api-fixture','name':'Official API','adapter':'BIZINFO','config':{}}
    pid,vid,run=uuid4(),uuid4(),uuid4()
    class Connection:
        def execute(self,*args,**kwargs):return SimpleNamespace(fetchone=lambda:{'id':run},fetchall=lambda:[])
    class Database:
        def transaction(self):return nullcontext(Connection())
        def save_program(self,*args,**kwargs):return {'program_id':pid,'version_id':vid,'event':None}
    def factory(s):
        if s['adapter']=='BIZINFO':
            copied=program.model_copy(update={'title':TITLE.replace('[마감]','')})
            found=Candidate(s['slug'],'api-id',URL,URL,copied.title,{'bsnsSumryCn':'Official API still lists the formal future deadline'})
            return SimpleNamespace(discover=lambda:iter([found]),normalize=lambda *args:copied,
                pagination=SimpleNamespace(report=lambda:{'pagination_complete':True}))
        adapter=OfficialChannelAdapter(s,Mock())
        adapter.discover=lambda:iter([candidate])
        adapter.fetch_detail=lambda _:AcquiredDetail(URL,BODY,TITLE,raw_metadata=candidate.raw_metadata)
        adapter.pagination.complete=True
        return adapter
    result=ingest(Database(),[api,source],adapter_factory=factory,structured_only=True)
    assert result['status']=='SUCCESS' and result['weekly_programs']==[]
    direct=result['sources'][1]
    assert direct['coverage']['excluded_records']==1
    assert direct['coverage']['decisions'][0]['reason']=='CLOSED_SOURCE_STATUS'
