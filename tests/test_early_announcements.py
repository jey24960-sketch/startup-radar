"""Narrow early-announcement policy and delivery safety tests."""
from datetime import datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4
import os

import pytest
from core.clock import SEOUL
from radar.early_announcements import (
    MINIMUM_LEAD, candidate_decision, next_weekly_at, announcement_text,
    plan_early_notices, announce_early,
)

AT = datetime(2026,10,28,12,tzinfo=SEOUL)  # Wednesday; next digest is November 3.


@pytest.fixture(autouse=True)
def verified_current_sources(monkeypatch):
    def latest(db,connection,reference,items):
        return {str(i['program_id']):{'version_id':i['program_version_id'],'snapshot':i['snapshot']} for i in items}
    monkeypatch.setattr('radar.early_announcements._latest_candidates',latest)


def facts(**updates):
    return {
        'title':'예비창업자 MVP 제작 및 액셀러레이팅 프로그램 모집',
        'organization':'공식 창업 지원기관',
        'support_summary':'예비창업팀의 MVP 제품 개발과 고객 검증, 시제품 제작, 사업화 지원을 제공하는 액셀러레이팅 프로그램입니다.',
        'applicant_summary':'예비창업자 및 초기 창업팀을 대상으로 합니다.',
        'application_start_at':(AT+timedelta(days=1)).isoformat(),
        'application_end_at':(AT+timedelta(days=8)).isoformat(),
        'application_start_precision':'DATETIME','application_end_precision':'DATETIME',
        'deadline_type':'FIXED_DATE','official_url':'https://example.org/program',
        **updates,
    }


def test_weekly_due_is_tuesday_seoul_and_strictly_future():
    assert next_weekly_at(AT)==datetime(2026,11,3,9,tzinfo=SEOUL)
    exact=datetime(2026,11,3,9,tzinfo=SEOUL)
    assert next_weekly_at(exact)==exact+timedelta(days=7)
    assert next_weekly_at(exact-timedelta(seconds=1))==exact
    with pytest.raises(ValueError): next_weekly_at(AT.replace(tzinfo=None))


def test_exception_requires_seven_full_days_and_cannot_wait_for_digest():
    assert MINIMUM_LEAD==timedelta(days=7)
    assert candidate_decision(facts(),AT)==(True,'SEVEN_DAY_WINDOW_LOST_IF_WAITING')
    assert candidate_decision(facts(application_end_at=(AT+timedelta(days=7)).isoformat()),AT)[0]
    assert candidate_decision(facts(application_end_at=(AT+timedelta(days=7)-timedelta(seconds=1)).isoformat()),AT)==(False,'UNDER_SEVEN_DAYS')
    enough=next_weekly_at(AT)+timedelta(days=7)
    assert candidate_decision(facts(application_end_at=enough.isoformat()),AT)==(False,'CAN_WAIT_FOR_WEEKLY')


@pytest.mark.parametrize('patch',[
    {'deadline_type':'ROLLING','application_end_at':None},
    {'deadline_type':'UNKNOWN'},
    {'application_end_precision':'UNKNOWN'},
    {'application_end_at':'2026-12-01T00:00:00'},
    {'application_end_at':'bad'},
])
def test_unverified_or_ongoing_deadlines_never_become_exceptions(patch):
    assert candidate_decision(facts(**patch),AT)==(False,'FIXED_VERIFIED_DEADLINE_REQUIRED')


def test_upcoming_is_preannounced_but_invalid_period_is_not():
    assert candidate_decision(facts(),AT)[0]
    assert candidate_decision(facts(application_start_at=(AT+timedelta(days=9)).isoformat()),AT)==(False,'INVALID_PERIOD')
    assert candidate_decision(facts(application_start_at='tomorrow'),AT)==(False,'INVALID_PERIOD')


def test_general_attendance_and_conditional_recruitment_are_not_important_exceptions():
    event=facts(title='창업 지원기관 데모데이 참관객 모집',support_summary='창업 관련 세미나와 데모데이 참관객을 모집합니다.')
    assert not candidate_decision(event,AT)[0]
    conditional=facts(applicant_summary='법인 설립 필수, 업력 7년 이상 기업만 신청할 수 있습니다.')
    assert not candidate_decision(conditional,AT)[0]
    assert candidate_decision(facts(official_url='javascript:alert(1)'),AT)==(False,'OFFICIAL_URL_REQUIRED')


def test_message_is_bounded_escaped_and_links_to_early_article():
    notice={'id':uuid4(),'title':'10월 28일자 중요 모집 사전 안내'}
    text=announcement_text(notice,[{'snapshot':facts(title='예비창업자 <MVP> 제작 지원'),'stage_codes':['STAGE_3']}])
    assert '&lt;MVP&gt;' in text and '<MVP>' not in text
    assert '/notice/early/'+str(notice['id']) in text
    assert '최소 7일' in text


class Result:
    def __init__(self, rows): self.rows=rows
    def fetchone(self): return self.rows[0] if self.rows else None
    def fetchall(self): return self.rows


class FakeConnection:
    def __init__(self, notice, now=AT, items=None, enabled=True, visible=True, running=True):
        self.notice=notice; self.now=now; self.items=items or [{'snapshot':facts(),'stage_codes':['STAGE_3']}]
        for item in self.items:
            item.setdefault('program_id',uuid4());item.setdefault('program_version_id',uuid4())
        self.enabled=enabled; self.visible=visible; self.running=running; self.updated=[]
    def execute(self,query,params=()):
        if query.startswith('select * from startup_radar.early_notices'): return Result([self.notice])
        if query.startswith('select now()'): return Result([{'reference_at':self.now}])
        if query.startswith('select program_id,program_version_id,snapshot,stage_codes'): return Result(self.items)
        if 'select value from startup_radar.runtime_settings' in query:
            key=params[0]
            value={
                'early_announcements':{'enabled':self.enabled,'active_from':(AT-timedelta(days=1)).isoformat()},
                'radar_operation':{'enabled':self.running},
                'radar_visibility':{'mode':'MEMBERS_ONLY' if self.visible else 'PRIVATE'},
                'weekly_telegram_channel':{'enabled':True,'chat_id':'fixture-channel','name':'GFC StartupRadar'},
            }[key]
            return Result([{'value':value}])
        if query.startswith('update startup_radar.early_notices'):
            self.updated.append((query,params))
            if 'delivery_state=%s' in query:self.notice['delivery_state']=params[0]
            elif "set delivery_state='SENDING'" in query: self.notice['delivery_state']='SENDING'
            elif "delivery_state='EXPIRED'" in query:self.notice['delivery_state']='EXPIRED'
            return Result([])
        raise AssertionError(query)


class FakeDatabase:
    def __init__(self,connection):self.connection=connection
    def transaction(self):
        from contextlib import nullcontext
        return nullcontext(self.connection)


def notice(state='PENDING'):
    return {'id':uuid4(),'title':'중요 모집 사전 안내','status':'PUBLISHED','withdrawn_at':None,
            'week_start':datetime(2026,10,26,tzinfo=SEOUL).date(),'published_at':AT,
            'delivery_state':state,'item_count':1}


@pytest.mark.parametrize('state',['SENDING','DELIVERED','UNCERTAIN','FAILED','EXPIRED'])
def test_nonpending_delivery_is_never_retried(state):
    row=notice(state); c=FakeConnection(row); send=Mock()
    assert announce_early(FakeDatabase(c),row['id'],send)['state']==state
    send.send.assert_not_called()


@pytest.mark.parametrize('state',['DELIVERED','FAILED','UNCERTAIN'])
def test_send_is_claimed_once_and_repeated_calls_do_not_duplicate(state):
    row=notice(); c=FakeConnection(row); send=Mock()
    send.send.return_value={'state':state,'receipt':{'message_id':17} if state=='DELIVERED' else None}
    first=announce_early(FakeDatabase(c),row['id'],send,AT)
    second=announce_early(FakeDatabase(c),row['id'],send,AT)
    assert first['state']==second['state']==state
    assert send.send.call_count==1
    assert any("delivery_state='SENDING'" in query for query,_ in c.updated)


def test_final_send_rechecks_deadline_and_does_not_send_short_runway():
    row=notice(); c=FakeConnection(row,items=[{'snapshot':facts(application_end_at=(AT+timedelta(days=6)).isoformat()),'stage_codes':['STAGE_3']}]); send=Mock()
    assert announce_early(FakeDatabase(c),row['id'],send,AT)['state']=='EXPIRED'
    send.send.assert_not_called()


@pytest.mark.parametrize('kwargs,expected',[
    ({'running':False},'PAUSED'),({'visible':False},'VISIBILITY_PRIVATE'),({'enabled':False},'EARLY_NOTICES_DISABLED')])
def test_operator_gates_suppress_external_send(kwargs,expected):
    row=notice(); c=FakeConnection(row,**kwargs); send=Mock()
    assert announce_early(FakeDatabase(c),row['id'],send,AT)['state']==expected
    send.send.assert_not_called()


def test_invalid_transport_receipt_is_uncertain_not_delivered():
    row=notice(); c=FakeConnection(row); send=Mock(); send.send.return_value={'state':'DELIVERED'}
    assert announce_early(FakeDatabase(c),row['id'],send,AT)['state']=='UNCERTAIN'


def test_changed_or_unverified_source_prevents_sending_a_stale_snapshot(monkeypatch):
    monkeypatch.setattr('radar.early_announcements._latest_candidates',lambda *args: {})
    row=notice(); c=FakeConnection(row); send=Mock()
    assert announce_early(FakeDatabase(c),row['id'],send,AT)['state']=='EXPIRED'
    send.send.assert_not_called()


def test_planner_reuses_existing_week_and_never_collects_or_sends(monkeypatch):
    # The existing worker claim owns concurrency; planning still serializes
    # publication with the weekly lock and has no transport or ingestion call.
    row=notice(); c=FakeConnection(row)
    original=c.execute
    def execute(query,params=()):
        if query.startswith('select pg_advisory_xact_lock'):return Result([])
        if query.startswith('select id from startup_radar.early_notices'):return Result([{'id':row['id']}])
        return original(query,params)
    c.execute=execute
    result=plan_early_notices(FakeDatabase(c),AT,candidates=[])
    assert result=={'state':'WEEKLY_EXCEPTION_LIMIT','planned':0,'notice_id':str(row['id'])}
