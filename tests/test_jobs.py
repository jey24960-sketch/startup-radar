import os
from types import SimpleNamespace
from uuid import uuid4
import pytest
import requests
from test_database import db
from radar.jobs import dispatch_job,cancel_job
from radar.scheduler import run_job

pytestmark=pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Explicit ephemeral database required')


@pytest.mark.parametrize('outcome',['ACCEPTED','REJECTED','TIMEOUT'])
def test_dispatch_response_never_overwrites_completed_job(db,monkeypatch,outcome):
    monkeypatch.setenv('RADAR_GITHUB_TOKEN','fixture-only')
    def post(*args,**kwargs):
        job_id=kwargs['json']['inputs']['job_id']
        result=run_job(db,'INGEST',job_id=job_id,executor=lambda *a,**k:{'status':'SUCCESS','proof':'fixture executed'})
        assert result['status']=='SUCCESS'
        if outcome=='TIMEOUT':raise requests.Timeout()
        return SimpleNamespace(status_code=204 if outcome=='ACCEPTED' else 503)
    monkeypatch.setattr('radar.jobs.requests.post',post)
    result=dispatch_job(db,'INGEST')
    assert result['state']=='SUCCESS'
    with db.transaction() as c:
        row=c.execute('select * from radar.job_requests where id=%s',(result['job_id'],)).fetchone()
        assert row['state']=='SUCCESS' and row['result']['proof']=='fixture executed'


def admin(db):
    user=uuid4()
    with db.transaction() as c:
        c.execute('insert into auth.users values(%s)',(user,))
        c.execute('insert into radar.admin_users values(%s)',(user,))
    return user


@pytest.mark.parametrize('initial',['REQUESTED','UNCERTAIN','RUNNING'])
def test_cancelled_request_blocks_late_workflow_and_is_audited(db,initial):
    user=admin(db)
    with db.transaction() as c:job=c.execute('insert into radar.job_requests(kind,state) values(%s,%s) returning id',('INGEST',initial)).fetchone()['id']
    assert cancel_job(db,job,'Verified orphan fixture; retire request',user)['state']=='CANCELLED'
    def unexpected(*args,**kwargs):raise AssertionError('Cancelled job executed')
    result=run_job(db,'INGEST',job_id=job,executor=unexpected)
    assert result['executed'] is False
    assert cancel_job(db,job,'Repeated cancellation',user)['changed'] is False
    with db.transaction() as c:
        rows=c.execute("select * from radar.admin_audit where action='CANCEL_JOB'").fetchall()
        assert len(rows)==1 and rows[0]['detail']['state']==initial


def test_cancel_requires_admin_and_preserves_terminal_job(db):
    user=admin(db);other=uuid4()
    with db.transaction() as c:
        c.execute('insert into auth.users values(%s)',(other,))
        job=c.execute("insert into radar.job_requests(kind,state) values('INGEST','SUCCESS') returning id").fetchone()['id']
    with pytest.raises(PermissionError):cancel_job(db,job,'Unauthorized cancellation',other)
    with pytest.raises(ValueError):cancel_job(db,job,'Completed jobs remain intact',user)


@pytest.mark.skipif(os.environ.get('TEST_NATIVE_POSTGRES')!='1',reason='Native lock exclusion required')
def test_cancel_cannot_race_running_job(db):
    user=admin(db)
    with db.transaction() as c:job=c.execute("insert into radar.job_requests(kind,state) values('INGEST','RUNNING') returning id").fetchone()['id']
    with db.transaction() as lock:
        lock.execute('select pg_advisory_xact_lock(782394202)')
        with pytest.raises(ValueError,match='currently running'):cancel_job(db,job,'Try cancelling live fixture',user)
    with db.transaction() as c:assert c.execute('select state from radar.job_requests where id=%s',(job,)).fetchone()['state']=='RUNNING'
