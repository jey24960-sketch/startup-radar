"""Requires a real multi-connection PostgreSQL server, not the PGlite multiplexer."""
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4
import pytest
from test_database import db,source,program
from radar.models import TeamProfile
from radar.scheduler import run_job,tick
from radar.recommendations import refresh_recommendations
from radar.notifications import plan_notifications,deliver_pending
from core.clock import now

pytestmark=pytest.mark.skipif(os.environ.get('TEST_NATIVE_POSTGRES')!='1',reason='Explicit native PostgreSQL test run required')


def test_concurrent_identical_program_has_one_version(db):
    p=program();s=source(db)
    def save(_):return db.save_program(p,s,'same-source-id',p.official_url,{},'identical source')
    with ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(save,range(12)))
    assert len({r['program_id'] for r in results})==1 and len({r['version_id'] for r in results})==1
    with db.transaction() as c:assert c.execute('select count(*) n from startup_radar.program_versions').fetchone()['n']==1


def test_global_job_lock_rejects_parallel_execution(db):
    started=threading.Event();release=threading.Event();calls=[]
    def execute(*args,**kwargs):
        calls.append(1);started.set()
        assert release.wait(10)
        return {'status':'SUCCESS'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(run_job,db,'INGEST',executor=execute)
        assert started.wait(5)
        try:
            second=run_job(db,'INGEST',executor=execute)
            assert second['status']=='FAILED' and 'Another V2 job' in second['error']
        finally:release.set()
        assert first.result(timeout=10)['status']=='SUCCESS'
    assert len(calls)==1


def test_cadence_claim_is_atomic_between_ticks(db):
    calls=[];guard=threading.Lock()
    def execute(db,kind,**kwargs):
        with guard:calls.append(kind)
        return {'status':'SUCCESS'}
    at=now().replace(hour=23)
    with ThreadPoolExecutor(max_workers=5) as pool:
        results=list(pool.map(lambda _:tick(db,at=at,executor=execute),range(5)))
    assert calls.count('INGEST')==1 and calls.count('REMINDER')==1
    assert len(calls)==len(set(calls))


def test_parallel_planners_and_senders_respect_daily_cap(db):
    owner=uuid4()
    with db.transaction() as c:c.execute('insert into auth.users values(%s)',(owner,))
    team=db.create_team('Concurrent fixture',owner,TeamProfile())
    s=source(db)
    for index in range(8):
        p=program();p.title+=str(index);p.program_types=['EDUCATION'];p.evidence_complete=True;p.application_end_at=now()+timedelta(days=15)
        db.save_program(p,s,str(index),p.official_url,{},'Fixture')
    with db.transaction() as c:c.execute('insert into startup_radar.telegram_subscriptions(team_id,chat_id,high_fit_threshold,channel_health) values(%s,%s,0,$health$HEALTHY$health$)',(team['id'],'fixture-concurrent'))
    refresh_recommendations(db)
    with ThreadPoolExecutor(max_workers=6) as pool:planned=list(pool.map(lambda _:plan_notifications(db,'HIGH_FIT'),range(6)))
    assert sum(planned)==2
    class Transport:
        def __init__(self):self.messages=[];self.lock=threading.Lock()
        def send(self,chat,text):
            with self.lock:
                self.messages.append(text)
                return {'state':'DELIVERED','receipt':{'message_id':len(self.messages)}}
    transport=Transport()
    with ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(lambda _:deliver_pending(db,transport,'HIGH_FIT'),range(6)))
    assert len(transport.messages)==2 and len(set(transport.messages))==2
    assert sum(r['delivered'] for r in results)==2
