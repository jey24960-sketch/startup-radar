"""Offline configuration check and portable production web entry point.

Never prints configuration values or contacts external services. A successful
check means configuration is present, not that credentials or deployment work.
"""
import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = {
    'web': ('DATABASE_URL', 'SUPABASE_URL', 'SUPABASE_PUBLISHABLE_KEY'),
    'ingestion': ('DATABASE_URL', 'ANTHROPIC_API_KEY', 'KSTARTUP_API_KEY', 'BIZINFO_API_KEY'),
    'delivery': ('DATABASE_URL', 'TELEGRAM_BOT_TOKEN'),
    'webhook': ('DATABASE_URL', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_WEBHOOK_SECRET'),
    'dispatch': ('DATABASE_URL', 'RADAR_GITHUB_TOKEN', 'GITHUB_REPOSITORY', 'RADAR_GITHUB_REF'),
}


def configuration_report(component='all', environ=None, root=ROOT):
    environ = os.environ if environ is None else environ
    selected = REQUIRED if component == 'all' else {component: REQUIRED[component]}
    checks = {}
    for name, variables in selected.items():
        missing = [key for key in variables if not environ.get(key, '').strip()]
        checks[name] = {'status': 'MISSING' if missing else 'PRESENT', 'missing': missing}
    if 'web' in checks:
        missing_assets = [name for name in ('index.html', 'app.js', 'style.css', 'base.css')
                          if not (root / 'web' / 'static' / name).is_file()]
        checks['assets'] = {'status': 'MISSING' if missing_assets else 'PRESENT', 'missing': missing_assets}
        try:
            port = int(environ.get('PORT', '8000'))
            valid_port = 1 <= port <= 65535
        except (ValueError, TypeError):
            valid_port = False
        checks['port'] = {'status': 'PRESENT' if valid_port else 'INVALID'}
    return {'status': 'CONFIGURED' if all(c['status'] == 'PRESENT' for c in checks.values()) else 'INCOMPLETE',
            'checks': checks, 'external_connections_verified': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--component', choices=['all', *REQUIRED], default='all')
    parser.add_argument('--serve', action='store_true', help='Check web configuration, then serve on PORT (default 8000)')
    args = parser.parse_args(argv)
    report = configuration_report('web' if args.serve else args.component)
    print(json.dumps(report, ensure_ascii=False), flush=True)
    if report['status'] != 'CONFIGURED':
        return 1
    if args.serve:
        import uvicorn
        uvicorn.run('radar.web:app', host='0.0.0.0', port=int(os.environ.get('PORT', '8000')),
                    proxy_headers=False)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
