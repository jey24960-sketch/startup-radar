import hashlib
import json
import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode


def normalize_text(value):
    return re.sub(r'[^\w가-힣]+','',unicodedata.normalize('NFKC',value).casefold())


def normalize_url(value):
    parts=urlsplit(value)
    # Yonsei's board appends the listing page to every pinned detail link.
    # The numeric path is the notice identity; p is only return navigation.
    # Keep p on the listing and on other hosts, where it may identify content.
    yonsei_notice=(parts.hostname or '').lower()=='venture.yonsei.ac.kr' and bool(
        re.fullmatch(r'/community/notice/\d+/?',parts.path))
    query=[(k,v) for k,v in parse_qsl(parts.query,keep_blank_values=True)
           if not k.lower().startswith('utm_') and k.lower() not in ('fbclid','gclid')
           and not (yonsei_notice and k=='p')]
    return urlunsplit((parts.scheme.lower(),parts.netloc.lower(),parts.path.rstrip('/') or '/',urlencode(sorted(query)),''))


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()


def duplicate_confidence(left,right):
    """Candidate score ONLY. Ambiguous/fuzzy matches never auto-merge."""
    if normalize_url(left['official_url'])==normalize_url(right['official_url']): return 1.0
    title=SequenceMatcher(None,normalize_text(left['title']),normalize_text(right['title'])).ratio()
    org=normalize_text(left['organization'])==normalize_text(right['organization'])
    return round(title*0.7+(0.25 if org else 0),3)


# One real opportunity is routinely carried by both national portals under
# different publisher IDs, different canonical hosts and different responsible
# organizations (ministry vs executing agency), so neither publisher identity
# nor URL nor organization can link the two records. What does not drift is the
# notice title once punctuation and spacing are normalized, together with the
# exact official application period. Requiring all three, plus a title specific
# enough that collision is implausible, keeps this deterministic, not fuzzy.
CROSS_SOURCE_TITLE_MIN=20


def _instant(value):
    if value in (None,''):return None
    if isinstance(value,datetime):parsed=value
    else:
        try:parsed=datetime.fromisoformat(str(value))
        except ValueError:return None
    if parsed.tzinfo is None:return None
    return parsed.timestamp()


def cross_source_key(title,start,end):
    """Stable identity for the same notice republished by another official portal.

    Returns None whenever the facts are too generic to assert identity safely.
    Callers must treat None as "no cross-source claim", never as a match.
    """
    normalized=normalize_text(str(title or ''))
    if len(normalized)<CROSS_SOURCE_TITLE_MIN:return None
    opened,closed=_instant(start),_instant(end)
    if opened is None or closed is None:return None
    return digest({'title':normalized,'start':opened,'end':closed})


def deduplicate_publication(rows):
    """Collapse one notice republished by a second official portal.

    Keeps the first occurrence and returns (kept,dropped). Rows whose facts are
    too generic for a safe cross-source claim are always kept.
    """
    kept,dropped,seen,detail_seen=[],[],{},{}
    for row in rows:
        facts=row['snapshot']
        # Old rows may already have different source IDs for a pinned notice.
        # Suppress those copies at publication without merging stored evidence.
        # This route has a publisher-assigned numeric ID. Exact title, organizer
        # and declared periods still distinguish reused or changed editions.
        url=facts.get('official_url') or ''
        parts=urlsplit(url)
        detail_key=None
        if ((parts.hostname or '').lower()=='venture.yonsei.ac.kr'
                and re.fullmatch(r'/community/notice/\d+/?',parts.path)
                and facts.get('title') and facts.get('organization')):
            detail_key=digest({'url':normalize_url(url),
                'title':normalize_text(facts['title']),
                'organization':normalize_text(facts['organization']),
                'start':facts.get('application_start_at'),
                'end':facts.get('application_end_at')})
        key=cross_source_key(facts.get('title'),facts.get('application_start_at'),
                             facts.get('application_end_at'))
        duplicate=detail_seen.get(detail_key) if detail_key is not None else None
        if duplicate is None and key is not None:duplicate=seen.get(key)
        if duplicate is not None:
            dropped.append({**row,'duplicate_of':str(duplicate['program_id'])})
            continue
        if detail_key is not None:detail_seen[detail_key]=row
        if key is not None:seen[key]=row
        kept.append(row)
    return kept,dropped


MATERIAL_FIELDS=('title','organization','program_types','application_start_at','application_end_at',
 'deadline_type','application_url','applicant_summary','benefit_summary','support_summary',
 'amount_min','amount_max','requirements','document_hashes','evidence_complete')


def changed_fields(old,new):
    return [key for key in MATERIAL_FIELDS if old.get(key)!=new.get(key)]
