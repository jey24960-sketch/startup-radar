"""Private, explicitly reviewed publication decisions; source facts stay intact.

Exclusions, holds and verified duplicate aliases persist until an operator
deactivates them. Text corrections also survive parser-only versions with exact
unchanged source evidence and facts. Publisher revisions require fresh review.
"""
from copy import deepcopy

PATCH_KEYS = frozenset(('support_summary', 'applicant_summary', 'organization'))
OPERATOR_KEYS = ('excInsttNm', 'jrsdInsttNm', 'pbanc_ntrp_nm', 'sprv_inst')


def _compatible_source_versions(reviewed, current):
    """Exact evidence equivalence; never fuzzy text or a date/identity bypass."""
    if not reviewed or not current or str(reviewed['program_id']) != str(current['program_id']):
        return False
    text = reviewed.get('raw_text')
    if not isinstance(text, str) or not text.strip() or current.get('raw_text') != text:
        return False
    before = reviewed.get('normalized') or {}
    after = current.get('normalized') or {}
    if {k: v for k, v in before.items() if k not in PATCH_KEYS} != {
            k: v for k, v in after.items() if k not in PATCH_KEYS}:
        return False
    old_sources = reviewed.get('source_operators') or {}
    new_sources = current.get('source_operators') or {}
    common = old_sources.keys() & new_sources.keys()
    return bool(common) and all(old_sources[key] == new_sources[key] for key in common)


def apply_reviews(candidates, reviews):
    by_program = {str(r['program_id']): r for r in reviews if r.get('active', True)}
    kept, withheld = [], {}
    for original in candidates:
        row = deepcopy(original)
        review = by_program.get(str(row['program_id']))
        if not review:
            kept.append(row)
            continue
        disposition = review['disposition']
        if disposition != 'RETAIN':
            reason = 'REVIEWED_' + disposition
            withheld[reason] = withheld.get(reason, 0) + 1
            continue
        versions = {str(review['reviewed_version_id']),
                    *(str(v) for v in review.get('compatible_version_ids') or [])}
        if str(row['version_id']) in versions:
            patch = review.get('snapshot_patch') or {}
            if set(patch) - PATCH_KEYS:
                raise ValueError('Publication review may only repair descriptive facts')
            row['snapshot'].update(patch)
            row['snapshot'].pop('review_note', None)
            row['publication_review'] = review
        kept.append(row)
    return kept, withheld


def load_reviews(c, candidates):
    if not candidates:
        return candidates, {}
    rows = c.execute('select * from startup_radar.publication_reviews '
                     'where active and program_id=any(%s::uuid[])',
                     ([str(r['program_id']) for r in candidates],)).fetchall()
    retained = [row for row in rows if row['disposition'] == 'RETAIN']
    if retained:
        version_ids = {str(row['version_id']) for row in candidates}
        version_ids.update(str(row['reviewed_version_id']) for row in retained)
        # The original immutable observations establish publisher operator facts;
        # a parser may intentionally correct the normalized organization label.
        # Every other normalized fact (including dates, precision and URLs) must
        # stay exactly equal. View-counter/body changes conservatively fail this
        # check rather than being normalized away as an assumed harmless edit.
        operator_fields = ','.join(f"'{key}',o.raw_metadata->'{key}'" for key in OPERATOR_KEYS)
        versions = c.execute(
            'select v.id,v.program_id,v.normalized,v.raw_text,coalesce(('
            'select jsonb_object_agg(o.source_id::text,jsonb_build_object(' + operator_fields + ')) '
            'from (select distinct on(ss.source_id) ss.source_id,ss.raw_metadata '
            ' from startup_radar.program_source_snapshots ss '
            ' where ss.program_version_id=v.id and ss.program_id=v.program_id '
            ' order by ss.source_id,ss.observed_at desc,ss.id desc) o),'
            "'{}'::jsonb) source_operators from startup_radar.program_versions v "
            'where v.id=any(%s::uuid[])', (list(version_ids),)).fetchall()
        by_version = {str(version['id']): version for version in versions}
        for row in retained:
            reviewed = by_version.get(str(row['reviewed_version_id']))
            row['compatible_version_ids'] = [str(candidate['version_id']) for candidate in candidates
                if str(candidate['program_id']) == str(row['program_id'])
                and _compatible_source_versions(reviewed, by_version.get(str(candidate['version_id'])))]
    return apply_reviews(candidates, rows)


def reviewed_classification(row, decision):
    review = row.get('publication_review')
    if not review:
        return decision
    status = review['relevance_status']
    return {**decision, 'relevance_status': status, 'startup_leverage': 'HIGH',
            'applicability': 'BROAD' if status == 'GFC_RELEVANT' else 'RESTRICTED',
            'restriction_summary': review.get('restriction_summary'),
            'startup_leverage_reason': review['reason'],
            'classification_method': 'REVIEWED_SOURCE_FACTS',
            'evidence': {**decision.get('evidence', {}),
                         'publication_review': {'version_id': str(review['reviewed_version_id']),
                                                'reason': review['reason']}}}
