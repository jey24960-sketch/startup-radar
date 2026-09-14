from contextlib import contextmanager
import pytest
from tools.benchmark_member_results import require_test_database


class FakeDatabase:
    def __init__(self,url,marker='ephemeral-test-only'):
        self.url=url;self.marker=marker;self.queries=[]
    @contextmanager
    def transaction(self):yield self
    def execute(self,query):self.queries.append(query);return self
    def fetchone(self):return {'value':self.marker}


@pytest.mark.parametrize('url',[
    'postgresql://production.example/db',
    'postgresql://localhost/db?hostaddr=203.0.113.1',
    'postgresql://localhost/db?host=production.example',
    'host=127.0.0.1 service=production dbname=db',
    'dbname=db',
])
def test_load_benchmark_rejects_remote_or_ambiguous_connection_before_connect(url):
    db=FakeDatabase(url)
    with pytest.raises(ValueError):require_test_database(db)
    assert db.queries==[]


def test_load_benchmark_requires_marker_even_for_loopback():
    db=FakeDatabase('postgresql://127.0.0.1/test','not-a-test')
    with pytest.raises(ValueError):require_test_database(db)
    assert db.queries==['select value from public.radar_test_marker']
    db.marker='ephemeral-test-only'
    require_test_database(db)
