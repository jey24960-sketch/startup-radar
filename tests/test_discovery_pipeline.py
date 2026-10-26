import json
import os
from uuid import uuid4
import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.pq import PipelineStatus, TransactionStatus
import pytest
from radar.database import Database
from radar.discovery_connection import SETTING, discovery_database_options
from test_database import db, program, source

POOLER = 'aws-1-ap-south-1.pooler.supabase.com'
DIRECT = 'db.fixtureproject.supabase.co'
SECRET = 'fixture-only-do-not-log-password'
URL = f'postgresql://postgres.fixture:{SECRET}@{POOLER}:6543/postgres?sslmode=require&connect_timeout=10'
native = pytest.mark.skipif(
    not os.environ.get('TEST_DATABASE_URL') or os.environ.get('TEST_NATIVE_POSTGRES') != '1',
    reason='Explicit native PostgreSQL test database required; pipeline is not forced through PGlite',
)


@pytest.mark.parametrize('value', ['', 'false', ' FALSE '])
def test_discovery_pipeline_is_default_off_and_does_not_parse_or_route_the_url(value):
    assert discovery_database_options({SETTING: value, 'DATABASE_URL': 'not parsed'}) == {}
    assert discovery_database_options({}) == {}
    assert Database('fixture-only-url').pipeline is False


@pytest.mark.parametrize('value', [None, 0, 1, 'true', 'false'])
def test_database_pipeline_option_requires_an_actual_boolean(value):
    with pytest.raises(ValueError, match='must be a boolean'):
        Database('fixture-only-url', pipeline=value)


def test_shared_transaction_pooler_routes_only_to_same_account_host_and_options_on_5432():
    options = discovery_database_options({SETTING: 'true', 'DATABASE_URL': URL})
    original = conninfo_to_dict(URL)
    assert options['pipeline'] is True
    assert conninfo_to_dict(options['url']) == {**original, 'port': '5432'}


@pytest.mark.parametrize('host', [POOLER, DIRECT])
def test_existing_session_and_direct_routes_remain_unchanged(host):
    url = f'postgresql://postgres:{SECRET}@{host}:5432/postgres?sslmode=require'
    assert discovery_database_options({SETTING: 'TRUE', 'DATABASE_URL': url}) == {'url': url, 'pipeline': True}


def test_an_omitted_port_is_explicitly_pinned_instead_of_inheriting_pgport():
    url = f'postgresql://postgres:{SECRET}@{DIRECT}/postgres'
    options = discovery_database_options({SETTING: 'true', 'DATABASE_URL': url, 'PGPORT': '6543'})
    assert conninfo_to_dict(options['url']) == {**conninfo_to_dict(url), 'port': '5432'}


@pytest.mark.parametrize('url', [
    f'postgresql://user:{SECRET}@{DIRECT}:6543/postgres',
    f'postgresql://user:{SECRET}@example.invalid:5432/postgres',
    f'postgresql://user:{SECRET}@{POOLER}.example.invalid:6543/postgres',
    f'postgresql://user:{SECRET}@localhost:5432/postgres',
    f'host={POOLER},other.pooler.supabase.com port=6543 dbname=postgres password={SECRET}',
    f'host={POOLER} port=5432 hostaddr=127.0.0.1 password={SECRET}',
    f'host={POOLER} port=5432 service=fixture password={SECRET}',
    f'{SECRET} invalid-conninfo',
])
def test_ambiguous_or_unsupported_routes_fail_without_connection_or_secret_in_error(url):
    with pytest.raises(ValueError) as caught:
        discovery_database_options({SETTING: 'true', 'DATABASE_URL': url})
    assert SECRET not in str(caught.value)
    assert url not in str(caught.value)


@pytest.mark.parametrize('variable', ['PGHOSTADDR', 'PGSERVICE'])
def test_environment_endpoint_overrides_are_not_silently_accepted(variable):
    with pytest.raises(ValueError, match='one explicit supported'):
        discovery_database_options({SETTING: 'true', 'DATABASE_URL': URL, variable: 'fixture'})


@pytest.mark.parametrize('value', ['1', 'yes', True])
def test_invalid_opt_in_values_are_rejected(value):
    with pytest.raises(ValueError, match='true or false'):
        discovery_database_options({SETTING: value, 'DATABASE_URL': URL})


def test_cli_opt_in_is_used_only_for_discover(monkeypatch, capsys):
    from radar.cli import main
    calls = []
    monkeypatch.setenv(SETTING, 'true')
    monkeypatch.setenv('DATABASE_URL', URL)
    monkeypatch.delenv('PGHOSTADDR', raising=False)
    monkeypatch.delenv('PGSERVICE', raising=False)
    monkeypatch.setattr('radar.cli.Database', lambda **kwargs: calls.append(kwargs) or object())
    monkeypatch.setattr('radar.discovery.run_discovery', lambda *_args, **_kwargs: {'status': 'SUCCESS'})
    monkeypatch.setattr('radar.weekly.run_weekly', lambda *_args, **_kwargs: {'status': 'SUCCESS'})
    assert main(['discover']) == 0
    assert calls[0]['pipeline'] is True and conninfo_to_dict(calls[0]['url'])['port'] == '5432'
    assert main(['weekly']) == 0
    assert calls[1] == {}
    assert SECRET not in capsys.readouterr().out


def test_probe_refuses_to_connect_without_opt_in(monkeypatch, capsys):
    from tools.probe_discovery_pipeline import main
    monkeypatch.delenv(SETTING, raising=False)
    monkeypatch.setattr('tools.probe_discovery_pipeline.Database', lambda **_kwargs: pytest.fail('Probe opened a database without opt-in'))
    assert main() == 1
    assert json.loads(capsys.readouterr().out) == {'status': 'FAILED', 'error_type': 'ValueError'}


def test_probe_failure_output_never_includes_driver_exception_or_connection_info(monkeypatch, capsys):
    from tools.probe_discovery_pipeline import main
    monkeypatch.setenv(SETTING, 'true')
    monkeypatch.setenv('DATABASE_URL', URL)
    monkeypatch.delenv('PGHOSTADDR', raising=False)
    monkeypatch.delenv('PGSERVICE', raising=False)
    monkeypatch.setattr('tools.probe_discovery_pipeline.Database', lambda **_kwargs: object())
    def failed(_db):
        raise psycopg.OperationalError(f'Cannot connect to {URL}')
    monkeypatch.setattr('tools.probe_discovery_pipeline.probe_database', failed)
    assert main() == 1
    output = capsys.readouterr().out
    assert json.loads(output) == {'status': 'FAILED', 'error_type': 'OperationalError'}
    assert SECRET not in output and POOLER not in output


@native
def test_native_pipeline_probe_rolls_back_delayed_error_and_reuses_idle_connection():
    from tools.probe_discovery_pipeline import probe_database
    result = probe_database(Database(os.environ['TEST_DATABASE_URL'], pipeline=True))
    assert result['status'] == 'SUCCESS' and all(result['checks'].values())


@native
def test_native_pipeline_applies_only_to_borrowed_transactions_and_preserves_actor_isolation():
    database = Database(os.environ['TEST_DATABASE_URL'], pipeline=True)
    actor, outer_identity = uuid4(), uuid4()
    with database.transaction() as unborrowed:
        assert unborrowed.info.pipeline_status == PipelineStatus.OFF
    with database.session():
        with database.transaction() as outer:
            assert outer.info.pipeline_status == PipelineStatus.ON
            outer.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(outer_identity),))
            outer_user = outer.execute('select current_user name').fetchone()['name']
            with database.transaction(actor) as nested:
                assert nested is not outer
                assert nested.info.pipeline_status == PipelineStatus.OFF
                assert nested.execute('select current_user name').fetchone()['name'] == 'authenticated'
                assert nested.execute("select current_setting('request.jwt.claim.sub',true) identity").fetchone()['identity'] == str(actor)
            assert outer.execute('select current_user name').fetchone()['name'] == outer_user
            assert outer.execute("select current_setting('request.jwt.claim.sub',true) identity").fetchone()['identity'] == str(outer_identity)
        assert outer.info.transaction_status == TransactionStatus.IDLE
        assert outer.info.pipeline_status == PipelineStatus.OFF
        with database.transaction() as subsequent:
            assert subsequent is outer
            assert subsequent.execute("select nullif(current_setting('request.jwt.claim.sub',true),'') identity").fetchone()['identity'] is None
    assert outer.closed


@native
def test_native_default_session_never_enables_pipeline():
    database = Database(os.environ['TEST_DATABASE_URL'])
    with database.session():
        with database.transaction() as connection:
            assert connection.info.pipeline_status == PipelineStatus.OFF
            assert connection.execute('select 1 value').fetchone()['value'] == 1
        assert connection.info.transaction_status == TransactionStatus.IDLE


@native
def test_native_pipeline_preserves_identical_versions_new_observations_and_quality(db):
    database = Database(db.url, pipeline=True)
    pid_source, facts = source(db), program()
    with database.session():
        first = database.save_program(facts, pid_source, 'pipeline-fixture', facts.official_url,
                                      {'revision': 1}, 'Official unchanged text')
        second = database.save_program(facts, pid_source, 'pipeline-fixture', facts.official_url,
                                       {'revision': 1}, 'Official unchanged text')
        third = database.save_program(facts, pid_source, 'pipeline-fixture', facts.official_url,
                                      {'revision': 2}, 'Official unchanged text')
        assert first['program_id'] == second['program_id'] == third['program_id']
        assert first['version_id'] == second['version_id'] == third['version_id']
        assert second['event'] is None and third['event'] is None
        with database.transaction() as c:
            assert c.execute('select count(*) n from startup_radar.program_versions where program_id=%s', (first['program_id'],)).fetchone()['n'] == 1
            assert c.execute('select count(*) n from startup_radar.program_source_snapshots where program_id=%s', (first['program_id'],)).fetchone()['n'] == 2
            assert c.execute('select count(*) n from startup_radar.program_quality where program_version_id=%s', (first['version_id'],)).fetchone()['n'] == 1
            version = c.execute('select last_observed_at from startup_radar.program_versions where id=%s', (first['version_id'],)).fetchone()
            assert version['last_observed_at'] is not None
