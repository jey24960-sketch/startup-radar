"""The bounded official API window for the GFC weekly publication only."""

POLICY = 'GFC_WEEKLY_V1'


def weekly_sources(sources):
    return [{**source, 'config': {**source['config'],
        'scope': 'OPEN' if source['adapter']=='KSTARTUP' else 'API_DEFAULT',
        'page_size': 100, 'max_pages': 1, 'weekly_policy': POLICY}}
        for source in sources]


def source_completed(source, legacy=False):
    coverage=source.get('coverage',{})
    if source.get('status')=='SUCCESS' and coverage.get('pagination_complete'):
        return not source.get('failures')
    # PAGE_LIMIT is acceptable only after every obtained record was persisted.
    # Missing identities, stalled pages and actual source failures remain failures.
    failures=source.get('failures',[])
    if (source.get('status')!='PARTIAL' or not failures
        or any(f.get('kind')!='PAGE_LIMIT' for f in failures)):
        return False
    if not legacy and coverage.get('weekly_policy')!=POLICY:return False
    if coverage.get('scope') not in ('OPEN','API_DEFAULT'):return False
    cap=coverage.get('page_cap');size=coverage.get('page_size')
    if any(type(n) is not int or not 1<=n<=100 for n in (cap,size)):return False
    if cap!=1:return False
    parsed=source.get('parsed',0)
    if not (parsed>0 and source.get('discovered')==source.get('fetched')==parsed
        and coverage.get('persisted_records')==coverage.get('unique_source_ids')==parsed
        and coverage.get('failed_records')==coverage.get('rejected_records')==0):
        return False
    queries=coverage.get('queries',[])
    return bool(queries) and all(q.get('pagination_complete') or
        (q.get('pages_requested')==cap and q.get('unique_records',0)>0)
        for q in queries)


def collection_completed(sources, legacy=False):
    return len(sources)==2 and all(source_completed(s,legacy) for s in sources)
