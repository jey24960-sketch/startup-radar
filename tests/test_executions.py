import os
import subprocess
import sys
from uuid import uuid4
from unittest.mock import patch
import psycopg
import pytest
from test_database import db
from radar.scheduler import run_job
from radar.executions import active_execution,claim_execution,finish_execution,recover_execution

pytestmark=pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Explicit ephemeral PostgreSQL required')


def test_completed_and_failed_executors_release_owner_and_preserve_ledger(db):
    first=run_job(db,'REFRESH',executor=lambda *a,**k:{'status':'SUCCESS','proof':'fixture'})
    assert active_execution(db) is None
    def fail(*a,**k):raise ValueError('Fixture failure')
    second=run_job(db,'REFRESH',executor=fail)
    assert second['status']=='FAILED' and active_execution(db) is None
    with db.transaction() as c:
        rows=c.execute('select id,state,result,owner from startup_radar.worker_executions order by started_at').fetchall()
    assert [r['state'] for r in rows]==['SUCCESS','FAILED']
    assert rows[0]['result']['proof']=='fixture' and rows[1]['result']['error']=='ValueError'
    assert all(set(r['owner'])=={'host','pid','github_run_id','github_run_attempt'} for r in rows)


def test_finalization_failure_is_uncertain_and_does_not_release_or_restart(db):
    with patch('radar.executions.finish_execution',side_effect=psycopg.OperationalError('fixture disconnect')):
        result=run_job(db,'REFRESH',executor=lambda *a,**k:{'status':'SUCCESS'})
    assert result['status']=='UNCERTAIN'
    assert str(active_execution(db)['id'])==result['execution_id']
    assert run_job(db,'REFRESH',executor=lambda *a,**k:pytest.fail('overlap'))['status']=='FAILED'
    recover_execution(db,result['execution_id'],'Fixture executor has returned; no external work',True)


def test_recovery_requires_confirmation_and_never_releases_another_owner(db):
    owner=claim_execution(db,'REFRESH')['execution_id']
    with pytest.raises(ValueError,match='stopped'):recover_execution(db,owner,'Fixture',False)
    with pytest.raises(ValueError,match='note'):recover_execution(db,owner,'x',True)
    with pytest.raises(LookupError):recover_execution(db,uuid4(),'Wrong fixture owner',True)
    assert str(active_execution(db)['id'])==owner
    recovered=recover_execution(db,owner,'Fixture has no executor and cannot resume',True)
    assert recovered['changed'] and not recovered['retry_dispatched']
    second=claim_execution(db,'REFRESH')['execution_id']
    assert recover_execution(db,owner,'Repeat stale fixture recovery',True)['changed'] is False
    assert str(active_execution(db)['id'])==second
    with pytest.raises(ValueError,match='ownership'):finish_execution(db,owner,{'status':'SUCCESS'})
    assert str(active_execution(db)['id'])==second
    finish_execution(db,second,{'status':'SUCCESS'})


def test_recovery_marks_request_uncertain_without_resetting_schedule_claims(db):
    with db.transaction() as c:
        job=c.execute("insert into startup_radar.job_requests(kind) values('TICK') returning id").fetchone()['id']
        c.execute("insert into startup_radar.schedule_claims(task_key,kind,state) values('fixture-claim','INGEST','RUNNING')")
    owner=claim_execution(db,'TICK',job_id=job)['execution_id']
    recover_execution(db,owner,'Verified stopped fixture owner; inspect partial effects',True)
    with db.transaction() as c:
        assert c.execute('select state from startup_radar.job_requests where id=%s',(job,)).fetchone()['state']=='UNCERTAIN'
        assert c.execute("select state from startup_radar.schedule_claims where task_key='fixture-claim'").fetchone()['state']=='RUNNING'


@pytest.mark.parametrize('role',['anon','authenticated'])
def test_execution_ledger_is_not_exposed_to_client_roles(db,role):
    owner=claim_execution(db,'REFRESH')['execution_id']
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with db.transaction() as c:
            c.execute('set local role '+role)
            c.execute('select * from startup_radar.worker_executions')
    finish_execution(db,owner,{'status':'SUCCESS'})


def test_short_claim_connections_close_but_ownership_does_not_expire(db):
    owner=claim_execution(db,'REFRESH')['execution_id']
    with db.transaction() as c:
        # Simulate an arbitrarily old claim; elapsed time grants no takeover.
        c.execute("update startup_radar.worker_executions set started_at=now()-interval '30 days' where id=%s",(owner,))
    assert run_job(db,'REFRESH',executor=lambda *a,**k:pytest.fail('expired owner taken over'))['status']=='FAILED'
    finish_execution(db,owner,{'status':'SUCCESS'})


@pytest.mark.skipif(os.environ.get('TEST_NATIVE_POSTGRES')!='1',reason='Native separate process required')
def test_process_exit_leaves_durable_owner_until_verified_recovery(db):
    code="""import os
from radar.database import Database
from radar.scheduler import run_job
def crash(*args,**kwargs):os._exit(7)
run_job(Database(os.environ['TEST_DATABASE_URL']),'REFRESH',executor=crash)
"""
    process=subprocess.run([sys.executable,'-c',code],timeout=20)
    assert process.returncode==7
    owner=active_execution(db)
    assert owner and owner['state']=='RUNNING'
    assert run_job(db,'REFRESH',executor=lambda *a,**k:pytest.fail('crashed owner ignored'))['status']=='FAILED'
    recover_execution(db,owner['id'],'subprocess returned exit code 7; fixture has terminated',True)
    assert run_job(db,'REFRESH',executor=lambda *a,**k:{'status':'SUCCESS'})['status']=='SUCCESS'


def test_cancel_request_cannot_bypass_durable_owner(db):
    from test_jobs import admin
    from radar.jobs import cancel_job
    user=admin(db)
    with db.transaction() as c:job=c.execute("insert into startup_radar.job_requests(kind) values('INGEST') returning id").fetchone()['id']
    owner=claim_execution(db,'INGEST',job_id=job)['execution_id']
    with pytest.raises(ValueError,match='currently running'):cancel_job(db,job,'Do not bypass durable owner',user)
    recover_execution(db,owner,'Fixture claim never ran an executor',True)
    assert cancel_job(db,job,'Now the fixture owner is recovered',user)['state']=='CANCELLED'


@pytest.mark.skipif(os.environ.get('TEST_NATIVE_POSTGRES')!='1',reason='Native backend fault injection required')
def test_connection_loss_while_executor_lives_does_not_admit_another_executor(db):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    started=threading.Event();release=threading.Event();backend=[]
    def execute(*args,**kwargs):
        with db.transaction() as c:
            backend.append(c.execute('select pg_backend_pid() pid').fetchone()['pid'])
            started.set()
            assert release.wait(15)
            c.execute('select 1')
        return {'status':'SUCCESS'}
    with ThreadPoolExecutor(max_workers=1) as pool:
        first=pool.submit(run_job,db,'REFRESH',executor=execute)
        assert started.wait(5)
        try:
            with db.transaction() as c:
                assert c.info.host=='127.0.0.1' and c.info.dbname=='radar_test'
                assert c.execute('select pg_terminate_backend(%s) terminated',(backend[0],)).fetchone()['terminated']
            blocked=run_job(db,'REFRESH',executor=lambda *a,**k:pytest.fail('executor overlap after disconnect'))
            assert blocked['status']=='FAILED'
        finally:release.set()
        assert first.result(timeout=10)['status']=='FAILED'
    assert active_execution(db) is None


@pytest.mark.parametrize('failed_commit',[1,2])
def test_lost_commit_acknowledgement_never_runs_an_unconfirmed_owner(db,failed_commit):
    from contextlib import contextmanager
    class LostAcknowledgement:
        commits=0
        @contextmanager
        def transaction(self):
            with db.transaction() as c:yield c
            self.commits+=1
            if self.commits==failed_commit:raise psycopg.OperationalError('Fixture lost commit acknowledgement')
    calls=[]
    def execute(*a,**k):calls.append(1);return {'status':'SUCCESS'}
    if failed_commit==1:
        with pytest.raises(psycopg.OperationalError):run_job(LostAcknowledgement(),'REFRESH',executor=execute)
        assert calls==[] and active_execution(db) is not None
        recover_execution(db,active_execution(db)['id'],'Claim caller returned without entering executor',True)
    else:
        result=run_job(LostAcknowledgement(),'REFRESH',executor=execute)
        assert result['status']=='UNCERTAIN' and calls==[1]
        # The executor is terminal and finalization actually committed. Inspect
        # that state instead of blindly rerunning this logical task.
        assert active_execution(db) is None
        with db.transaction() as c:
            assert c.execute('select state from startup_radar.worker_executions where id=%s',(result['execution_id'],)).fetchone()['state']=='SUCCESS'
