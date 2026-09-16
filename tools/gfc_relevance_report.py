"""Read-only dry run of the publication correction.

Reads an exported snapshot of currently published briefing items, applies
exactly the production rules in the production order

    cross-source dedup -> actionability -> GFC relevance

and reports what would remain visible. It writes nothing to any database.

    python -m tools.gfc_relevance_report export.json --json-out plan.json

`export.json` is a list of objects with `publication_kind`, `program_id`,
`display_order` and the stored editorial snapshot fields, plus a `references`
map giving the original publication/snapshot timestamp per publication kind.
Each briefing is judged at its own original reference time, so history is not
re-judged with a later clock.
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime

from radar.actionability import actionability
from radar.identity import deduplicate_publication
from radar.relevance import PUBLISHABLE_STATUSES, RELEVANCE_VERSION, classify

SECTION_RANK = {'GFC_RELEVANT': 0, 'CONDITIONAL': 1}
SNAPSHOT_FIELDS = ('title', 'organization', 'applicant_summary', 'support_summary',
                   'application_start_at', 'application_end_at', 'deadline_type',
                   'application_end_precision')


def as_row(record):
    return {'program_id': record['program_id'], 'change_type': record.get('change_type'),
            'display_order': record.get('display_order'),
            'snapshot': {key: record.get(key) for key in SNAPSHOT_FIELDS}}


def evaluate(records, reference):
    rows = [as_row(record) for record in records]
    kept, duplicates = deduplicate_publication(rows)
    visible, withheld = [], []
    for row in kept:
        facts = row['snapshot']
        decision = classify(facts)
        publishable, reason = actionability(facts, reference)
        record = {**row, **decision}
        if not publishable:
            withheld.append({**record, 'stage': 'ACTIONABILITY', 'reason': reason})
            continue
        if decision['relevance_status'] not in PUBLISHABLE_STATUSES:
            withheld.append({**record, 'stage': 'RELEVANCE', 'reason': decision['relevance_status']})
            continue
        visible.append(record)
    visible.sort(key=lambda row: (SECTION_RANK[row['relevance_status']],
                                  row['snapshot'].get('application_end_at') or '9999',
                                  row['snapshot']['title'], str(row['program_id'])))
    for index, row in enumerate(visible):
        row['new_display_order'] = index
    return {'considered': len(rows), 'duplicates': duplicates,
            'visible': visible, 'withheld': withheld}


def report(kind, result, samples):
    actionability_counts = Counter(r['reason'] for r in result['withheld'] if r['stage'] == 'ACTIONABILITY')
    classes = Counter(r['relevance_status'] for r in result['withheld'] + result['visible'])
    print(f'\n================ {kind} ================')
    print(f'  considered                {result["considered"]}')
    print(f'  duplicates removed        {len(result["duplicates"])}')
    for reason in ('CLOSED', 'NEAR_DEADLINE', 'DEADLINE_UNKNOWN', 'UPCOMING'):
        print(f'  actionability {reason:<16} {actionability_counts.get(reason, 0)}')
    for status in ('GFC_RELEVANT', 'CONDITIONAL', 'OUT_OF_SCOPE', 'REVIEW_REQUIRED'):
        print(f'  relevance     {status:<16} {classes.get(status, 0)}')
    print(f'  FINAL VISIBLE             {len(result["visible"])}')

    buckets = defaultdict(list)
    for row in result['visible'] + [r for r in result['withheld'] if r['stage'] == 'RELEVANCE']:
        buckets[row['relevance_status']].append(row)
    for status in ('GFC_RELEVANT', 'CONDITIONAL', 'OUT_OF_SCOPE', 'REVIEW_REQUIRED'):
        rows = buckets.get(status, [])
        if not rows:
            continue
        print(f'\n  -- {status}: {len(rows)} total, showing {min(samples, len(rows))} --')
        for row in rows[:samples]:
            note = row.get('restriction_summary') or row.get('startup_leverage_reason') or ''
            print(f'   · {row["snapshot"]["title"][:70]}')
            print(f'       {note[:80]}')
    if result['duplicates']:
        print('\n  -- duplicates removed --')
        for row in result['duplicates']:
            print(f'   · {row["snapshot"]["title"][:70]} (dup of {row["duplicate_of"]})')


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('export')
    parser.add_argument('--samples', type=int, default=10)
    parser.add_argument('--json-out')
    args = parser.parse_args(argv)
    payload = json.loads(open(args.export, encoding='utf-8').read())
    grouped = defaultdict(list)
    for record in payload['items']:
        grouped[record['publication_kind']].append(record)
    plan = {}
    for kind, records in grouped.items():
        reference = datetime.fromisoformat(payload['references'][kind])
        result = evaluate(records, reference)
        report(kind, result, args.samples)
        plan[kind] = {'reference': payload['references'][kind],
                      'relevance_version': RELEVANCE_VERSION,
                      'visible': [{'program_id': row['program_id'],
                                   'display_order': row['new_display_order'],
                                   'relevance_status': row['relevance_status'],
                                   'restriction_summary': row['restriction_summary'],
                                   'relevance_version': RELEVANCE_VERSION}
                                  for row in result['visible']],
                      'withheld': [{'program_id': row['program_id'], 'stage': row['stage'],
                                    'reason': row['reason']} for row in result['withheld']],
                      'duplicates': [{'program_id': row['program_id'],
                                      'duplicate_of': row['duplicate_of']} for row in result['duplicates']]}
    if args.json_out:
        with open(args.json_out, 'w', encoding='utf-8') as handle:
            json.dump(plan, handle, ensure_ascii=False, indent=1)
        print(f'\nplan written to {args.json_out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
