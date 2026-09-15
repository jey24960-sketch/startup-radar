"""Bounded public-source validation. No database writes or announcements."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from radar.adapters.weekly_direct import OfficialChannelAdapter
from radar.adapters.base import SourceFailure
from radar.http import SafeHttp
from radar.opportunity_facts import weekly_decision
from core.clock import now


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--sources', default='weekly-direct-sources.json')
    parser.add_argument('--sample', type=int, choices=range(1, 6), default=3)
    parser.add_argument('--output', default='work/weekly-direct-validation.json')
    parser.add_argument('--slug')
    args = parser.parse_args()
    reports = []
    for source in json.loads(Path(args.sources).read_text(encoding='utf-8')):
        if args.slug and source['slug'] != args.slug:
            continue
        adapter = OfficialChannelAdapter(source, SafeHttp(source['config']['allowed_hosts'],max_bytes=3_000_000))
        report = {'source': source, 'checked_at': now().isoformat(),
                  'discovered': 0, 'records': [], 'failures': []}
        candidates = []
        try:
            for candidate in adapter.discover():
                candidates.append(candidate)
        except SourceFailure as error:
            report['failures'].append(error.record())
        report['discovered'] = len(candidates)
        for candidate in candidates[:args.sample]:
            try:
                detail = adapter.fetch_detail(candidate)
                program = adapter.normalize(candidate, detail, [])
                decision, reason = weekly_decision(program, candidate.raw_metadata['weekly_direct_facts'])
                record = {'candidate': asdict(candidate), 'detail': asdict(detail),
                          'program': program.model_dump(mode='json'),
                          'decision': decision, 'reason': reason}
                report['records'].append(record)
                print(json.dumps({'source': source['slug'], 'title': program.title,
                    'url': program.official_url, 'end': str(program.application_end_at),
                    'decision': decision, 'reason': reason}, ensure_ascii=True), flush=True)
            except SourceFailure as error:
                report['failures'].append(error.record(url=candidate.official_detail_url))
        report['coverage'] = adapter.pagination.report()
        reports.append(report)
        print(json.dumps({'source': source['slug'], 'discovered': len(candidates),
            'parsed_sample': len(report['records']), 'failures': report['failures']}), flush=True)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
