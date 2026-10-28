"""Explain batch outcomes in Actions without changing their failure semantics."""
from collections import Counter
from html import escape
import os
from pathlib import Path
import sys


def _cell(value):
    return escape(str(value)).replace('|', '&#124;').replace('\r', ' ').replace('\n', ' ')


def write_actions_report(command, result):
    destination = os.environ.get('GITHUB_STEP_SUMMARY')
    if not destination:
        return
    sources = result.get('sources') or []
    counts = Counter(source.get('status', 'UNKNOWN') for source in sources)
    persisted = sum((source.get('coverage') or {}).get('persisted_records', 0) or 0
                    for source in sources)
    status = result.get('status', 'UNKNOWN')
    if status == 'PARTIAL_SUCCESS':
        explanation = '일부 단계 실패·범위 제한이 있습니다. 수집·게시·전송 결과를 아래에서 별도로 확인하세요.'
    elif status == 'FAILED':
        explanation = '작업이 실패했습니다. 오류 로그와 저장·게시 여부를 확인하세요.'
    else:
        explanation = '실행 결과입니다. 수집과 게시·전송은 서로 다른 단계입니다.'
    lines = [f'## StartupRadar — {_cell(command)}', '',
             f'**{_cell(status)}** — {explanation}', '',
             f'- 수집처: {len(sources)}개 (완료 {counts["SUCCESS"]}, '
             f'부분 완료 {counts["PARTIAL"]}, 실패 {counts["FAILED"]})',
             f'- 저장한 원본 레코드: {persisted}건 (중복 사업을 포함할 수 있음)']
    if 'published' in result:
        publication = ('기존 게시 유지' if result.get('unchanged') else
                       '완료' if result['published'] else '새 게시 없음')
        item_count = f' · 항목 {result["item_count"]}개' if 'item_count' in result else ''
        lines.append(f'- 주간 공지 게시: {publication}{item_count}')
    announcement = result.get('announcement')
    if announcement is not None:
        lines.append(f'- 주간 알림 전송: {_cell(announcement.get("state", "UNKNOWN"))}'
                     f' · 실제 전송 {announcement.get("delivered", 0)}건')
        if announcement.get('states'):
            lines.append('- 전송 상태별 건수: ' + ', '.join(
                f'{_cell(state)}={_cell(count)}' for state, count in sorted(announcement['states'].items())))
    early = result.get('early_delivery')
    if early is not None:
        lines.append(f'- 사전 안내 전송: {_cell(early.get("state", "UNKNOWN"))}'
                     f' · 이번 실행 실제 전송 {early.get("delivered", 0)}건')
    if sources:
        lines.extend(['', '| 수집처 | 상태 | 저장 | 원인 코드 |', '|---|---|---:|---|'])
        for source in sources:
            failures = Counter(f.get('reason_code') or f.get('kind') or 'UNKNOWN'
                               for f in source.get('failures', []))
            reasons = ', '.join(f'{code} ×{count}' for code, count in sorted(failures.items())) or '—'
            lines.append('| ' + ' | '.join(map(_cell, [
                source.get('source_slug') or source.get('source_name', 'UNKNOWN'),
                source.get('status', 'UNKNOWN'),
                (source.get('coverage') or {}).get('persisted_records', 0), reasons])) + ' |')
        lines.extend(['', '`PAGE_LIMIT`, `RECORD_LIMIT`, `CHANNEL_BUDGET`은 안전 한도에 도달한 상태입니다. '
                      '전체 범위를 수집했다는 의미는 아닙니다.',
                      '`TLS_ERROR`는 외부 사이트의 보안 연결 검증 실패입니다. '
                      '`DETAIL_PARSE`는 읽을 수 있는 원문을 확정하지 못한 상태입니다.'])
    lines.append('')
    try:
        with Path(destination).open('a', encoding='utf-8') as stream:
            stream.write('\n'.join(lines))
    except OSError:
        # Reporting must not replace a completed collection/publication outcome.
        print('::warning::StartupRadar 실행 요약을 기록하지 못했습니다.', file=sys.stderr)
        return
    if status == 'PARTIAL_SUCCESS':
        print(f'::warning::StartupRadar 일부 단계 실패/범위 제한: {len(sources)}개 수집처, '
              f'{persisted}개 원본 레코드 저장. 게시·전송 결과와 원인은 실행 요약을 확인하세요.', file=sys.stderr)
