import hashlib
import json
import re
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode


def normalize_text(value):
    return re.sub(r'[^\w가-힣]+','',unicodedata.normalize('NFKC',value).casefold())


def normalize_url(value):
    parts=urlsplit(value)
    query=[(k,v) for k,v in parse_qsl(parts.query,keep_blank_values=True)
           if not k.lower().startswith('utm_') and k.lower() not in ('fbclid','gclid')]
    return urlunsplit((parts.scheme.lower(),parts.netloc.lower(),parts.path.rstrip('/') or '/',urlencode(sorted(query)),''))


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()


def duplicate_confidence(left,right):
    """Candidate score ONLY. Ambiguous/fuzzy matches never auto-merge."""
    if normalize_url(left['official_url'])==normalize_url(right['official_url']): return 1.0
    title=SequenceMatcher(None,normalize_text(left['title']),normalize_text(right['title'])).ratio()
    org=normalize_text(left['organization'])==normalize_text(right['organization'])
    return round(title*0.7+(0.25 if org else 0),3)


MATERIAL_FIELDS=('title','organization','program_types','application_start_at','application_end_at',
 'deadline_type','application_url','applicant_summary','benefit_summary','support_summary',
 'amount_min','amount_max','requirements','document_hashes','evidence_complete')


def changed_fields(old,new):
    return [key for key in MATERIAL_FIELDS if old.get(key)!=new.get(key)]
