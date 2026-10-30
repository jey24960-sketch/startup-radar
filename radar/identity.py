import hashlib
import json
import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode
from core.clock import SEOUL


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


def _identity_route(value):
    """An exact public route, never an expiring download or a homepage."""
    if not isinstance(value,str) or len(value)>2000:return None
    value=value.strip()
    if not value or re.search(r'\s',value):return None
    if '://' not in value:
        if not re.match(r'[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/',value):return None
        value='https://'+value
    try:
        parts=urlsplit(value)
        if parts.scheme not in ('http','https') or not parts.hostname or parts.username or parts.password:return None
        if not parts.path.strip('/') or parts.port not in (None,80,443):return None
        if re.search(r'(?:fileDownload|fileDown|getImageFile|download)',parts.path,re.I):return None
        if any(re.search(r'token|signature|credential|authorization|api[_-]?key|^sig$|^expires$|^x-amz-',key,re.I)
               for key,_ in parse_qsl(parts.query,keep_blank_values=True)):return None
        # This is corroborating identity only. It never changes/fetches the URL.
        return normalize_url(urlunsplit(('https',parts.hostname.lower(),parts.path,parts.query,'')))
    except ValueError:return None


def publication_identity_evidence(raw):
    """Carry structured publisher/application routes without hashing them as facts.

    Do not mine arbitrary page links, emails, titles or signed attachments.
    A shared route is corroboration, never sufficient duplicate evidence alone.
    """
    application=[raw.get(key) for key in ('aply_mthd_onli_rcpt_istc','biz_aply_url','rceptEngnHmpgUrl')]
    verified=raw.get('official_application_links')
    if isinstance(verified,list):application.extend(value for value in verified if isinstance(value,str))
    result={}
    for key,values in (('application_urls',application),('publisher_urls',[raw.get('biz_gdnc_url')])):
        routes=sorted({route for value in values if (route:=_identity_route(value))})
        if routes:result[key]=routes[:10]
    return result


def _corroborating_routes(facts):
    evidence=facts.get('identity_evidence')
    evidence=evidence if isinstance(evidence,dict) else {}
    values=[facts.get('application_url')]
    for key in ('application_urls','publisher_urls'):
        if isinstance(evidence.get(key),list):values.extend(evidence[key])
    return {route for value in values if (route:=_identity_route(value))}


def _date_compatible(left,right,key):
    a,b=left.get(key+'_at'),right.get(key+'_at')
    # A missing start/deadline is not repaired by a matching title or a reused
    # application form. Reviewed cross-posts with incomplete dates use operator
    # decisions instead of this automatic rule.
    if _instant(a) is None or _instant(b) is None:return False
    if left.get(key+'_precision')=='DATE' or right.get(key+'_precision')=='DATE':
        a=a if isinstance(a,datetime) else datetime.fromisoformat(str(a))
        b=b if isinstance(b,datetime) else datetime.fromisoformat(str(b))
        return a.astimezone(SEOUL).date()==b.astimezone(SEOUL).date()
    return _instant(a)==_instant(b)


def _route_duplicate(left,right):
    a,b=left['snapshot'],right['snapshot']
    title=normalize_text(str(a.get('title') or ''))
    if len(title)<CROSS_SOURCE_TITLE_MIN or title!=normalize_text(str(b.get('title') or '')):return False
    # Different publisher IDs on the same board remain authoritative.
    if not _different_publisher(a,b):return False
    return (bool(_corroborating_routes(a)&_corroborating_routes(b))
            and _date_compatible(a,b,'application_start') and _date_compatible(a,b,'application_end'))


def _different_publisher(left,right):
    hosts=[(urlsplit(facts.get('official_url') or '').hostname or '').lower().removeprefix('www.')
           for facts in (left,right)]
    return bool(all(hosts) and hosts[0]!=hosts[1])


def _publication_completeness(row):
    facts=row['snapshot']
    precise=sum(facts.get(key+'_precision')=='DATETIME' for key in ('application_start','application_end'))
    applicant=str(facts.get('applicant_summary') or '').strip()
    if applicant in ('공식 공고 확인 필요','전체','창업벤처','중소기업'):applicant=''
    return (precise,len(applicant),len(str(facts.get('support_summary') or '')))


def deduplicate_publication(rows):
    """Collapse one notice republished by a second official portal.

    Prefer precise dates and fuller audience facts, preserving input order for
    equal completeness. No source records or snapshots are merged/mutated.
    """
    kept,dropped,seen,detail_seen=[],[],{},{}
    ordered=sorted(enumerate(rows),key=lambda pair:tuple(-x for x in _publication_completeness(pair[1]))+(pair[0],))
    for _,row in ordered:
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
        if duplicate is None and key is not None:
            exact=[other for other in seen.get(key,[]) if _different_publisher(facts,other['snapshot'])]
            if len(exact)==1:duplicate=exact[0]
        if duplicate is None:
            corroborated=[other for other in kept if _route_duplicate(row,other)]
            # A coarser date may match two precise, conflicting editions. Do not
            # use that row to bridge them or arbitrarily select a representative.
            if len(corroborated)==1:duplicate=corroborated[0]
        if duplicate is not None:
            dropped.append({**row,'duplicate_of':str(duplicate['program_id'])})
            continue
        if detail_key is not None:detail_seen[detail_key]=row
        if key is not None:seen.setdefault(key,[]).append(row)
        kept.append(row)
    positions={id(row):index for index,row in enumerate(rows)}
    return sorted(kept,key=lambda row:positions[id(row)]),dropped


MATERIAL_FIELDS=('title','organization','program_types','application_start_at','application_end_at',
 'deadline_type','application_url','applicant_summary','benefit_summary','support_summary',
 'amount_min','amount_max','requirements','document_hashes','evidence_complete')


def changed_fields(old,new):
    return [key for key in MATERIAL_FIELDS if old.get(key)!=new.get(key)]
