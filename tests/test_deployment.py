import json
from radar.deployment import configuration_report, main, REQUIRED


def test_missing_configuration_never_leaks_values():
    report = configuration_report('all', {'DATABASE_URL': 'postgresql://private-secret'})
    assert report['status'] == 'INCOMPLETE'
    assert 'private-secret' not in json.dumps(report)
    assert 'DATABASE_URL' not in report['checks']['web']['missing']
    assert 'SUPABASE_URL' in report['checks']['web']['missing']
    assert report['external_connections_verified'] is False


def test_web_requires_built_assets_and_valid_port(tmp_path):
    env = {key: 'fixture-value' for key in REQUIRED['web']}
    assert configuration_report('web', env, tmp_path)['status'] == 'INCOMPLETE'
    static = tmp_path / 'web' / 'static'
    static.mkdir(parents=True)
    for name in ('index.html', 'app.js', 'style.css', 'base.css'):
        (static / name).write_text('fixture')
    assert configuration_report('web', env, tmp_path)['status'] == 'CONFIGURED'
    for port in ('0', '65536', 'invalid'):
        assert configuration_report('web', {**env, 'PORT': port}, tmp_path)['status'] == 'INCOMPLETE'


def test_missing_settings_prevent_server_start(monkeypatch, capsys):
    import uvicorn
    for key in REQUIRED['web']:
        monkeypatch.delenv(key, raising=False)
    def unexpected_start(*args, **kwargs):
        raise AssertionError('Server must not start without web configuration')
    monkeypatch.setattr(uvicorn, 'run', unexpected_start)
    assert main(['--serve']) == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'INCOMPLETE'


def test_configured_server_uses_production_entry_point(monkeypatch):
    import uvicorn
    for key in REQUIRED['web']:
        monkeypatch.setenv(key, 'fixture-value')
    monkeypatch.setenv('PORT', '9123')
    calls = []
    monkeypatch.setattr(uvicorn, 'run', lambda *args, **kwargs: calls.append((args, kwargs)))
    assert main(['--serve']) == 0
    assert calls == [(('radar.web:app',), {'host': '0.0.0.0', 'port': 9123, 'proxy_headers': False})]
