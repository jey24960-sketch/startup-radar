import json

from radar.actions_report import write_actions_report


def test_partial_collection_and_successful_publication_are_reported_separately(tmp_path, monkeypatch, capsys):
    summary = tmp_path / 'summary.md'
    monkeypatch.setenv('GITHUB_STEP_SUMMARY', str(summary))
    result = {'status': 'PARTIAL_SUCCESS', 'published': True, 'item_count': 146,
              'announcement': {'state': 'RECORDED', 'delivered': 1}, 'sources': [
                  {'source_slug': 'official-api', 'status': 'SUCCESS', 'coverage': {'persisted_records': 1420}},
                  {'source_slug': 'broken-site', 'status': 'FAILED', 'failures': [
                      {'kind': 'ROBOTS_UNAVAILABLE', 'reason_code': 'TLS_ERROR'}]},
                  {'source_slug': 'bounded', 'status': 'PARTIAL', 'coverage': {'persisted_records': 30},
                   'failures': [{'reason_code': 'PAGE_LIMIT'}]}]}
    original = json.dumps(result, sort_keys=True)
    write_actions_report('weekly', result)
    text = summary.read_text(encoding='utf-8')
    assert 'PARTIAL_SUCCESS' in text and '1450건' in text
    assert '주간 공지 게시: 완료 · 항목 146개' in text and '실제 전송 1건' in text
    assert 'TLS_ERROR ×1' in text and 'PAGE_LIMIT ×1' in text
    assert '전체 범위를 수집했다는 의미는 아닙니다' in text
    assert json.dumps(result, sort_keys=True) == original
    assert '::warning::StartupRadar 일부 단계 실패/범위 제한' in capsys.readouterr().err


def test_discovery_does_not_claim_a_weekly_publication(tmp_path, monkeypatch):
    summary = tmp_path / 'summary.md'
    monkeypatch.setenv('GITHUB_STEP_SUMMARY', str(summary))
    write_actions_report('discover', {'status': 'SUCCESS', 'sources': [],
                                     'early_delivery': {'state': 'DELIVERED', 'delivered': 0}})
    text = summary.read_text(encoding='utf-8')
    assert '주간 공지 게시' not in text
    assert '이번 실행 실제 전송 0건' in text


def test_existing_weekly_result_does_not_claim_a_new_empty_publication(tmp_path, monkeypatch):
    summary = tmp_path / 'summary.md'
    monkeypatch.setenv('GITHUB_STEP_SUMMARY', str(summary))
    write_actions_report('weekly', {'status': 'SUCCESS', 'published': True, 'unchanged': True,
                                    'briefing_id': 'existing-week'})
    text = summary.read_text(encoding='utf-8')
    assert '주간 공지 게시: 기존 게시 유지' in text
    assert '항목 0개' not in text


def test_delivery_failure_does_not_claim_the_successful_collector_failed(tmp_path, monkeypatch):
    summary = tmp_path / 'summary.md'
    monkeypatch.setenv('GITHUB_STEP_SUMMARY', str(summary))
    write_actions_report('weekly', {'status': 'PARTIAL_SUCCESS', 'published': True, 'item_count': 12,
        'sources': [{'source_slug': 'official-api', 'status': 'SUCCESS', 'coverage': {'persisted_records': 25}}],
        'announcement': {'state': 'RECORDED', 'delivered': 0, 'states': {'FAILED': 1}}})
    text = summary.read_text(encoding='utf-8')
    assert '일부 단계 실패' in text and '일부 수집 실패' not in text
    assert '완료 1, 부분 완료 0, 실패 0' in text
    assert '전송 상태별 건수: FAILED=1' in text


def test_report_escapes_source_text_and_never_includes_raw_failure_messages(tmp_path, monkeypatch):
    summary = tmp_path / 'summary.md'
    monkeypatch.setenv('GITHUB_STEP_SUMMARY', str(summary))
    write_actions_report('discover', {'status': 'PARTIAL_SUCCESS', 'sources': [
        {'source_slug': '<script>|\nname', 'status': 'FAILED', 'failures': [
            {'reason_code': 'TLS_ERROR', 'message': 'private message serviceKey=secret'}]}]})
    text = summary.read_text(encoding='utf-8')
    assert '<script>' not in text and '&lt;script&gt;&#124; name' in text
    assert 'secret' not in text


def test_summary_write_failure_does_not_change_run_outcome(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('GITHUB_STEP_SUMMARY', str(tmp_path))
    result = {'status': 'PARTIAL_SUCCESS', 'sources': []}
    write_actions_report('discover', result)
    assert result['status'] == 'PARTIAL_SUCCESS'
    assert '요약을 기록하지 못했습니다' in capsys.readouterr().err


def test_cli_preserves_nonzero_partial_exit_and_json_result(tmp_path, monkeypatch, capsys):
    from radar import cli, discovery
    summary = tmp_path / 'summary.md'
    monkeypatch.setenv('GITHUB_STEP_SUMMARY', str(summary))
    monkeypatch.setenv('RADAR_ACTIONS_REPORT', 'true')
    monkeypatch.setattr(cli, 'Database', lambda **kwargs: object())
    monkeypatch.setattr('radar.discovery_connection.discovery_database_options', lambda: {})
    monkeypatch.setattr(discovery, 'run_discovery', lambda *args, **kwargs: {
        'status': 'PARTIAL_SUCCESS', 'sources': []})
    assert cli.main(['discover']) == 1
    output = capsys.readouterr().out
    assert json.loads(output)['status'] == 'PARTIAL_SUCCESS'
    assert 'PARTIAL_SUCCESS' in summary.read_text(encoding='utf-8')
