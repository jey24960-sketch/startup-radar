from types import SimpleNamespace
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import anthropic
import httpx
import pytest
from core.clock import now
from radar.adapters.base import SourceFailure
from radar.analysis_cache import extract_cached,input_key
from radar.ai_requests import request,REQUEST_TIMEOUT
from test_database import db,source,program


@pytest.mark.parametrize('status,reason,retry_count',[(401,'AI_CREDENTIALS',1),(400,'AI_REQUEST',1),(429,'AI_RATE_LIMIT',2),(503,'AI_SERVER',2)])
def test_explicit_request_budget_and_sanitized_failure_usage(monkeypatch,status,reason,retry_count):
    calls=[];monkeypatch.setattr('radar.ai_requests.time.sleep',lambda _:None)
    def create(**kwargs):
        calls.append(kwargs)
        response=httpx.Response(status,request=httpx.Request('POST','https://api.anthropic.com/v1/messages'))
        raise anthropic.APIStatusError('PRIVATE_KEY',response=response,body={'secret':'PRIVATE_KEY'})
    metrics={}
    with pytest.raises(SourceFailure) as failure:request(SimpleNamespace(messages=SimpleNamespace(create=create)),metrics,model='fixture')
    assert failure.value.kind==reason and len(calls)==retry_count
    assert all(c['timeout']==REQUEST_TIMEOUT for c in calls)
    assert metrics['failed_calls']==metrics['usage_unknown_calls']==retry_count
    assert metrics['retry_calls']==retry_count-1 and 'PRIVATE_KEY' not in str(metrics)


def test_timeout_retry_then_success_records_actual_usage(monkeypatch):
    monkeypatch.setattr('radar.ai_requests.time.sleep',lambda _:None);calls=[]
    def create(**kwargs):
        calls.append(kwargs)
        if len(calls)==1:raise anthropic.APITimeoutError(request=httpx.Request('POST','https://api.anthropic.com'))
        return SimpleNamespace(model='fixture-model',usage=SimpleNamespace(input_tokens=120,output_tokens=30,cache_read_input_tokens=10,cache_creation_input_tokens=0))
    metrics={};request(SimpleNamespace(messages=SimpleNamespace(create=create)),metrics,model='fixture')
    assert metrics['request_count']==2 and metrics['successful_calls']==metrics['failed_calls']==1
    assert metrics['input_tokens']==120 and metrics['output_tokens']==30 and metrics['usage_unknown_calls']==1
    assert metrics['requests'][0]['reason_code']=='AI_TIMEOUT' and metrics['requests'][0]['input_tokens'] is None
    assert metrics['requests'][1]['latency_ms']>=0


def test_deterministic_failure_is_cached_until_changed_input_or_contract(db):
    p=program();sid=source(db);detail=SimpleNamespace(text='official fixture')
    class Extractor:
        version='one';calls=0
        def extract(self,*args):
            self.calls+=1
            raise SourceFailure('AI_SCHEMA','Invalid schema')
    e=Extractor();first={};cached={}
    for metadata in (first,cached):
        with pytest.raises(SourceFailure,match='AI_SCHEMA'):extract_cached(db,e,p,detail,[],sid,metadata)
    assert e.calls==1 and cached['cache_status']=='FAILURE_HIT' and cached['current_usage']['request_count']==0
    assert first['attempt_id']==cached['attempt_id']
    e.version='two'
    with pytest.raises(SourceFailure):extract_cached(db,e,p,detail,[],sid,{})
    assert e.calls==2


def test_transient_failure_backoff_and_budget_are_persistent(db,monkeypatch):
    p=program();sid=source(db);detail=SimpleNamespace(text='transient fixture');clock=[now()]
    monkeypatch.setattr('radar.analysis_cache.now',lambda:clock[0])
    class Extractor:
        calls=0
        def extract(self,*args):
            self.calls+=1
            raise SourceFailure('AI_TIMEOUT','Timed out',True)
    e=Extractor()
    for attempt in range(1,4):
        with pytest.raises(SourceFailure):extract_cached(db,e,p,detail,[],sid,{})
        assert e.calls==attempt
        with pytest.raises(SourceFailure):extract_cached(db,e,p,detail,[],sid,{})
        assert e.calls==attempt
        clock[0]+=timedelta(hours=2)
    with pytest.raises(SourceFailure):extract_cached(db,e,p,detail,[],sid,{})
    assert e.calls==3
    with db.transaction() as c:
        rows=c.execute('select * from startup_radar.extraction_attempts where source_id=%s order by attempt_number',(sid,)).fetchall()
    assert [r['attempt_number'] for r in rows]==[1,2,3] and not rows[-1]['retryable'] and rows[-1]['next_retry_at'] is None


@pytest.mark.skipif(__import__('os').environ.get('TEST_NATIVE_POSTGRES')!='1',reason='Native multi-session PostgreSQL required')
def test_ai_call_has_no_open_db_transaction_and_duplicate_call_is_blocked(db):
    p=program();sid=source(db);detail=SimpleNamespace(text='slow fixture')
    started=threading.Event();release=threading.Event()
    class Extractor:
        calls=0
        def extract(self,p,*args):
            self.calls+=1;started.set()
            assert release.wait(10)
            return p
    e=Extractor();key=input_key(e,p,detail,[],sid)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(extract_cached,db,e,p,detail,[],sid,{})
        assert started.wait(5)
        try:
            with db.transaction() as c:
                assert c.execute('select pg_try_advisory_xact_lock(%s) acquired',(int(key[:15],16),)).fetchone()['acquired']
                assert c.execute("select state from startup_radar.extraction_attempts where input_hash=%s",(key,)).fetchone()['state']=='RUNNING'
                assert c.execute("select count(*) n from pg_stat_activity where datname=current_database() and pid<>pg_backend_pid() and state='idle in transaction'").fetchone()['n']==0
            with pytest.raises(SourceFailure,match='AI_IN_PROGRESS'):extract_cached(db,e,p,detail,[],sid,{})
        finally:release.set()
        assert future.result(timeout=10)==p
    metadata={};assert extract_cached(db,e,p,detail,[],sid,metadata)==p
    assert e.calls==1 and metadata['current_usage']=={'request_count':0,'cache_hits':1}


def test_expired_owner_cannot_publish_late_result_or_be_automatically_retried(db):
    p=program();sid=source(db);detail=SimpleNamespace(text='expired fixture')
    class Extractor:
        calls=0
        def extract(self,p,*args):
            self.calls+=1
            with db.transaction() as c:c.execute("update startup_radar.extraction_attempts set lease_expires_at=now()-interval '1 second' where source_id=%s",(sid,))
            return p
    e=Extractor()
    for _ in range(2):
        with pytest.raises(SourceFailure,match='AI_OWNER_EXPIRED'):extract_cached(db,e,p,detail,[],sid,{})
    assert e.calls==1
    with db.transaction() as c:
        assert c.execute("select state from startup_radar.extraction_attempts where source_id=%s",(sid,)).fetchone()['state']=='UNCERTAIN'
        assert not c.execute('select 1 from startup_radar.extraction_cache where input_hash=%s',(input_key(e,p,detail,[],sid),)).fetchone()


def test_operator_retry_is_one_auditable_grant_without_erasing_failure(db):
    from radar.analysis_cache import request_extraction_retry
    p=program();sid=source(db);detail=SimpleNamespace(text='operator fixture')
    class Extractor:
        calls=0
        def extract(self,p,*args):
            self.calls+=1
            if self.calls==1:raise SourceFailure('AI_SCHEMA','Schema failure')
            return p
    e=Extractor()
    with pytest.raises(SourceFailure):extract_cached(db,e,p,detail,[],sid,{})
    key=input_key(e,p,detail,[],sid)
    granted=request_extraction_retry(db,key,'Verified provider correction; exact input only')
    assert not granted['executed'] and e.calls==1
    assert extract_cached(db,e,p,detail,[],sid,{})==p and e.calls==2
    with db.transaction() as c:
        rows=c.execute('select * from startup_radar.extraction_attempts where input_hash=%s order by attempt_number',(key,)).fetchall()
        assert rows[0]['state']=='FAILED' and rows[0]['error_kind']=='AI_SCHEMA' and not rows[0]['operator_retry_allowed']
        assert rows[1]['state']=='SUCCESS'
        assert c.execute("select 1 from startup_radar.admin_audit where action='EXTRACTION_RETRY_ALLOWED' and entity_id=%s",(str(rows[0]['id']),)).fetchone()
