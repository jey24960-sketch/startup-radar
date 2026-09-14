import os
from concurrent.futures import ThreadPoolExecutor
import pytest
import psycopg
from psycopg.pq import TransactionStatus
from test_database import db
from test_web_runtime import context

pytestmark=pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Explicit ephemeral database required')


def test_batch_reuses_connection_but_never_role_identity_or_failed_transaction(context):
    c=context;db=c['db']
    with db.session():
        with db.transaction(c['admin']) as con:
            pid=con.info.backend_pid
            assert str(con.execute('select auth.uid() id').fetchone()['id'])==str(c['admin'])
        assert con.info.transaction_status==TransactionStatus.IDLE
        with pytest.raises(psycopg.errors.DivisionByZero):
            with db.transaction(c['other']) as other:
                assert other.info.backend_pid==pid
                assert str(other.execute('select auth.uid() id').fetchone()['id'])==str(c['other'])
                other.execute('select 1/0')
        assert con.info.transaction_status==TransactionStatus.IDLE
        with db.session():
            with db.transaction() as service:
                assert service.info.backend_pid==pid
                assert service.execute("select current_user name,nullif(current_setting('request.jwt.claim.sub',true),'') identity").fetchone()['identity'] is None
                assert service.execute('select current_user name').fetchone()['name']!='authenticated'
                with db.transaction(c['admin']) as nested:
                    assert nested.info.backend_pid!=pid
                    assert nested.execute('select current_user name').fetchone()['name']=='authenticated'
                assert service.execute('select current_user name').fetchone()['name']!='authenticated'
                assert service.execute("select nullif(current_setting('request.jwt.claim.sub',true),'') identity").fetchone()['identity'] is None
        def another_thread():
            with db.transaction() as worker:return worker.info.backend_pid
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(another_thread).result(timeout=10)!=pid
    assert con.closed
    assert db._session_connection.get() is None
