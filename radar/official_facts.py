"""Cached official HTML evidence for the inexpensive discovery path.

This reads public text only: no model calls, document OCR or eligibility guesses.
The original structured dates remain authoritative unless the same dated period
explicitly supplies a more precise time. Missing detail never destroys API facts.
"""
from datetime import datetime, timedelta
import re
import time
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from core.clock import now, SEOUL
from radar.adapters.base import SourceFailure
from radar.documents import html_text
from radar.identity import digest
from radar.relevance import classify, OUT_OF_SCOPE
from radar.opportunity_facts import labeled_period, explicit_closure

CACHE_KEY = '_official_detail'
MAX_TEXT = 24000
CACHE_AGE = timedelta(days=3)
FAILURE_AGE = timedelta(hours=2)
MAX_NEW_REQUESTS = 50
MAX_SOURCE_SECONDS = 120

# The acquired page is evidence, not a member-facing support description. These
# explicit publisher labels let us reuse cached HTML without putting navigation,
# contact fields, duplicate titles and the full announcement into that field.
DETAIL_MARKER = re.compile(r'(?m)^\s*공식 공고 상세\s*$')
_SUPPORT_LABELS = frozenset(('지원내용', '주요지원내용', '지원사항', '지원혜택',
                           '교육안내', '교육내용', '프로그램내용', '참여혜택',
                           '선정혜택', '참가혜택', '시상내역', '시상내용',
                           '행사개요', '사업개요', '지원프로그램', '주요지원'))
_APPLICANT_LABELS = frozenset(('신청대상', '지원대상', '모집대상', '참가대상',
                             '참여대상', '신청자격', '지원자격', '제외대상',
                             '신청제외대상', '지원제외대상', '참가자격',
                             '참여조건', '참가조건', '모집분야', '신청자격검토사항'))
_APPLICANT_LABELS |= frozenset(('교육대상', '참석대상', '수강대상', '참가신청대상'))
_OTHER_LABELS = frozenset(('신청방법및대상', '신청기간', '접수기간', '모집기간',
                         '신청방법', '접수방법', '제출서류', '제출방법',
                         '선정절차및평가방법', '선정절차', '평가방법', '문의처',
                         '문의', '연락처', '첨부파일', '기타사항', '유의사항',
                         '담당자', '담당자명', '개인정보처리방침', '이용약관',
                         '지원분야', '대상연령', '기관구분', '담당부서', '지역',
                         '주관기관명', '대상', '창업업력'))
_OTHER_LABELS |= frozenset(('모집개요', '대회개요', '신청안내', '접수안내', '신청링크',
                          '모집규모', '선정규모', '지원기간', '입주기간', '공급규모',
                          '입주조건', '월관리비', '추진일정', '추진체계',
                          '평가항목및평가방법', '평가항목', '신청방법및절차',
                          '참가비', '교육장소', '행사기간', '행사일시', '행사장소',
                          '사업신청방법', '사업신청사이트', '본문출력파일',
                          '해시태그목록', '태그', '첨부파일안내', '개인정보제공동의',
                          '이전글', '다음글', '목록', '목록으로', '목록으로돌아가기',
                          '신청하기', '지원하기', '공모일정', '심사기준', '지원방법', '자주묻는질문',
                          '소관부처·지자체', '사업수행기관', '수행기관', '운영기관'))
_GENERIC_APPLICANTS = frozenset(('중소기업', '소상공인', '창업벤처', '전체', '일반기업',
                               '공식 공고 확인 필요'))


def _join_unique(*parts):
    """Join overlapping whole blocks without deleting repeated lines in tracks.

    The same grant or mentoring line can legitimately belong to Display and
    new-business tracks. Global line-level deduplication silently erased it.
    """
    lines = []
    for part in parts:
        incoming = [line.strip() for line in (part or '').splitlines() if line.strip()]
        if not incoming:
            continue
        if any(lines[index:index+len(incoming)] == incoming
               for index in range(max(0, len(lines)-len(incoming)+1))):
            continue
        overlap = next((size for size in range(min(len(lines), len(incoming)), 0, -1)
                        if lines[-size:] == incoming[:size]), 0)
        lines.extend(incoming[overlap:])
    return '\n'.join(lines)


def _label(line):
    # Publisher section headings commonly start with emoji, squares or a numbered
    # prefix. Only normalize the candidate label; keep source value text verbatim.
    head, *tail = re.split(r'[:：]', line, maxsplit=1)
    head = re.sub(r'^[^가-힣A-Za-z0-9]+', '', head).strip()
    head = re.sub(r'^\d+[.)]\s*', '', head)
    head = head.strip('[]【】()（）')
    return re.sub(r'\s+', '', head), tail[0].strip() if tail else ''


def _applicant_summary(original, extracted):
    if str(original or '').strip() in _GENERIC_APPLICANTS:
        return extracted or original
    return _join_unique(original, extracted)


def performing_organization(text):
    """Read the publisher's explicit operator label, never infer from contacts."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for labels in (('사업수행기관', '수행기관', '운영기관'), ('주관기관', '주최기관', '주최')):
        for index, line in enumerate(lines):
            label, inline = _label(line)
            if label in labels:
                value = inline or (lines[index+1] if index+1 < len(lines) else '')
                if value and _label(value)[0] not in _OTHER_LABELS:
                    return value
    return None


def public_detail_fields(text):
    """Extract only explicitly labelled support/audience sections, never guess.

    Full source text remains in the immutable observation and _official_detail.
    Unknown page structures keep their structured API summaries as the fallback.
    This deliberately also accepts the already-cached plain text representation.
    """
    values = {'support_summary': [], 'applicant_summary': []}
    current = None
    labels = _SUPPORT_LABELS | _APPLICANT_LABELS | _OTHER_LABELS
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        label, inline = _label(line)
        # Institution-prefixed labels are still explicit source headings, e.g.
        # "IBK창공 선정기업 지원 내용" and "입주기업 지원내용".
        if len(label) <= 40 and re.fullmatch(r'.*(?:지원내용|지원혜택|선정혜택|참가혜택)', label):
            label = '지원내용'
        if label == '대상' and current == 'support_summary':
            # In a prize section this means the grand prize, not portal metadata.
            values[current].append(line)
            continue
        if label == '운영기간' and current == 'applicant_summary':
            current = None
            continue
        if current == 'support_summary' and label in (
                '참가비', '교육장소', '행사기간', '행사일시', '행사장소', '지원기간'):
            # These are attributes within an explicit support/education section,
            # not a new page section that should erase the remaining curriculum.
            values[current].append(line)
            continue
        if label in labels:
            current = ('support_summary' if label in _SUPPORT_LABELS else
                       'applicant_summary' if label in _APPLICANT_LABELS else None)
            if current and '제외' in label:
                values[current].append('제외대상')
            elif current and label == '모집분야':
                values[current].append('모집분야')
            if current and inline.strip():
                values[current].append(inline.strip())
            continue
        if re.match(r'상기\s*일정|신청\s*시\s*요청하는\s*정보|제출하신\s*서류|'
                    r'K-Startup에\s*공고|자세한\s*내용은\s*첨부파일|'
                    r'[#＃]\s*\S|스크랩\s*\d*|조회수\s*\d*|Copyright', line, re.I):
            current = None
        if current:
            values[current].append(line)
    fields = {key: _join_unique('\n'.join(lines)) for key, lines in values.items() if lines}
    if not fields.get('applicant_summary'):
        # This is an explicit publisher audience declaration, copied verbatim;
        # it is not an inference that all readers meet the condition.
        target = re.search(r'(?:에서는|에서)\s*([^.!?\n]{2,250}?)\s*(?:을|를)\s*대상으로', text)
        if target and re.search(r'기업|창업|개인|팀|학생|기관|단체', target[1]):
            fields['applicant_summary'] = target[1].strip()
    return fields


def bizinfo_summary_fields(text):
    """The API's first ☞ block is its explicit audience, not trgetNm's category.

    Only use this documented presentation when there are separate audience and
    support pointers; a lone pointer cannot safely establish the distinction.
    """
    fields = public_detail_fields(text)
    parts = re.split(r'☞\s*', fields.get('support_summary') or text)
    if len(parts) >= 3 and re.search(r'기업|창업|개인|국민|기관|단체|대학|팀|자치단체', parts[1]):
        fields['applicant_summary'] = parts[1].strip()
        fields['support_summary'] = _join_unique(parts[0], *parts[2:])
    return fields


def direct_public_fields(text, title='', source_slug=None):
    """Project public descriptions from a direct-source body without its chrome.

    A source without explicit support labels stays unknown rather than turning
    its whole page (including unrelated notices and contact details) into a benefit.
    """
    fields = (bizinfo_summary_fields(text) if '행사개요' in text or '사업개요' in text
              else public_detail_fields(text))
    if source_slug == 'weekly-naver-d2sf':
        # This approved source separates its current support package into
        # Value1/2/3 blocks before a distinct alumni-history section. Quotes and
        # named alumni below those blocks are testimonials, not applicant terms.
        package = re.search(r'(Value1\.[\s\S]+?)(?=투자\s*유치부터\s*M&A까지)', text)
        if package and 'Value2.' in package[1] and 'Value3.' in package[1]:
            support = re.sub(r'["“][\s\S]*?["”]', '', package[1])
            support = '\n'.join(line for line in support.splitlines()
                if not re.search(r'^\s*\*|^\s*[가-힣]{2,4}\s+.{0,30}대표\s*$', line))
            fields['support_summary'] = _join_unique(support)
    operator = performing_organization(text)
    if operator:
        fields['organization'] = operator
    return fields


def clean_legacy_snapshot(facts):
    """Repair only the known enrichment delimiter; preserve all other facts."""
    result = dict(facts)
    summary = str(result.get('support_summary') or '')
    marker = DETAIL_MARKER.search(summary)
    if marker is None:
        return result
    original, detail = summary[:marker.start()].strip(), summary[marker.end():].strip()
    fields = public_detail_fields(detail)
    result['support_summary'] = _join_unique(original, fields.get('support_summary'))
    if fields.get('applicant_summary'):
        result['applicant_summary'] = _applicant_summary(result.get('applicant_summary'), fields['applicant_summary'])
    return result


def evidence_signature(program, raw):
    """Ignore view counters, query totals and crawler timestamps."""
    facts = program.model_dump(mode='json')
    keys = ('title', 'organization', 'application_start_at', 'application_end_at',
            'application_start_precision', 'application_end_precision',
            'applicant_summary', 'support_summary', 'official_url', 'application_url')
    return digest({**{key: facts.get(key) for key in keys},
                   'attachments': {key: raw.get(key) for key in
                                   ('flpthNm', 'printFlpthNm', 'fileNm', 'printFileNm')}})


def should_enrich(program, reference=None):
    reference = reference or now()
    if program.application_end_at and program.application_end_at <= reference:
        return False
    return classify(program.model_dump(mode='json'))['relevance_status'] != OUT_OF_SCOPE


def _cached(db, source_id, source_program_id, signature, reference):
    if source_program_id is None:
        return None
    with db.transaction() as c:
        row = c.execute('select raw_metadata from startup_radar.program_sources '
                        'where source_id=%s and source_program_id=%s',
                        (source_id, source_program_id)).fetchone()
    item = (row.get('raw_metadata') or {}).get(CACHE_KEY) if row else None
    if not isinstance(item, dict) or item.get('signature') != signature:
        return None
    try:
        expiry = datetime.fromisoformat(item['expires_at'])
        if expiry.tzinfo is None or expiry <= reference:
            return None
    except (KeyError, ValueError, TypeError):
        return None
    return item


def _body(adapter, candidate):
    data, _, final_url = adapter.http.get(candidate.official_detail_url)
    # BizInfo currently serves nested HTML/body documents. lxml drops the real
    # notice in that response; html.parser preserves its explicit detail block.
    soup = BeautifulSoup(data, 'html.parser')
    selector = ('.support_project_detail' if adapter.source['adapter'] == 'BIZINFO'
                else '.app_notice_details-wrap')
    body = soup.select_one(selector)
    if body is None:
        raise SourceFailure('DETAIL_PARSE', 'Official notice body not found')
    for node in body.select('script,style,nav,.similar_announcement'):
        node.decompose()
    text = html_text(str(body)).strip()
    if not text or '\ufffd' in text:
        raise SourceFailure('DETAIL_PARSE', 'Official notice text unavailable')
    return text[:MAX_TEXT], final_url


def _precise_time(day, text):
    if day is None:
        return None
    day = day.astimezone(SEOUL)
    date = rf'{day.year}\s*[./-]\s*0?{day.month}\s*[./-]\s*0?{day.day}(?!\d)'
    times = set()
    # Restrict evidence to the labelled application period, never event dates,
    # publication dates, contacts or the related-opportunity widget.
    other_field = (r'(?:행사|교육|운영|사업|지원)\s*(?:일시|일정|기간|날짜|일)(?![가-힣])|'
                   r'신청\s*(?:방법|대상)|접수\s*방법|모집\s*대상|지원\s*내용|'
                   r'문의처|사업\s*개요|주관\s*기관|선정\s*절차|제출\s*서류|오리엔테이션')
    for section in re.finditer(r'(?:신청\s*기간|접수\s*기간|모집\s*기간)\s*[:：]?\s*', text):
        tail = text[section.end():section.end()+400]
        value = re.split(other_field, tail, maxsplit=1)[0]
        value = '\n'.join(value.splitlines()[:3])
        for match in re.finditer(date + r'\s*\.?\s*(?:\([가-힣A-Za-z]+\))?\s*(\d{1,2}):(\d{2})(?!\d)', value):
            hour, minute = map(int, match.groups())
            if hour < 24 and minute < 60:
                times.add((hour, minute))
    if len(times) != 1:
        return None
    hour, minute = times.pop()
    return day.replace(hour=hour, minute=minute, second=0, microsecond=0)


def apply_evidence(program, item):
    if item.get('status') != 'SUCCESS' or not item.get('text'):
        return program
    text = item['text'][:MAX_TEXT]
    cleaned = clean_legacy_snapshot(program.model_dump(mode='json'))
    is_bizinfo = urlsplit(program.official_url).hostname in ('www.bizinfo.go.kr', 'bizinfo.go.kr')
    fields = bizinfo_summary_fields(text) if is_bizinfo else public_detail_fields(text)
    updates = {'support_summary': _join_unique(cleaned.get('support_summary'), fields.get('support_summary'))}
    if fields.get('applicant_summary'):
        updates['applicant_summary'] = _applicant_summary(cleaned.get('applicant_summary'), fields['applicant_summary'])
    if is_bizinfo and performing_organization(text):
        updates['organization'] = performing_organization(text)
    _, detail_end, _, detail_end_precision, _ = labeled_period(text)
    if (detail_end and program.application_end_at and
            (detail_end.astimezone(SEOUL).date() != program.application_end_at.astimezone(SEOUL).date()
             or (program.application_end_precision == 'DATETIME' and detail_end_precision == 'DATETIME'
                 and detail_end != program.application_end_at))):
        # The structured API and publisher disagree on the closing day. Keep
        # both original declarations as evidence, not a guessed public deadline.
        updates.update(application_start_at=None, application_end_at=None,
                       application_start_precision='UNKNOWN', application_end_precision='UNKNOWN',
                       deadline_type='UNKNOWN')
        item['application_period_conflict'] = True
        return program.model_copy(update=updates)
    for field in ('application_start', 'application_end'):
        day = getattr(program, field + '_at')
        # A conflicting time does not overwrite a previously precise official
        # datetime. It needs source review rather than silent reconciliation.
        if getattr(program, field + '_precision') == 'DATE':
            precise = _precise_time(day, text)
            if precise:
                updates.update({field + '_at': precise, field + '_precision': 'DATETIME'})
    return program.model_copy(update=updates)


def enrich_official(db, source, adapter, candidate, program, reference=None):
    """Return program/evidence/diagnostic without spending any AI tokens."""
    reference = reference or now()
    signature = evidence_signature(program, candidate.raw_metadata)
    item = _cached(db, source['id'], candidate.source_program_id, signature, reference)
    cache_hit = item is not None
    if item is None:
        state = getattr(adapter, '_official_enrichment_budget', None)
        if state is None:
            state = {'started': time.monotonic(), 'requests': 0, 'blocked_hosts': set()}
            adapter._official_enrichment_budget = state
        host = urlsplit(candidate.official_detail_url).hostname
        if (host in state['blocked_hosts'] or state['requests'] >= MAX_NEW_REQUESTS or
                time.monotonic() - state['started'] >= MAX_SOURCE_SECONDS):
            # This declared optional-evidence budget never truncates the API
            # record scan. Deferred bodies are retried next run, not cached as
            # successful/complete or used to invent more specific facts.
            item = {'signature': signature, 'status': 'DEFERRED', 'reason': 'DETAIL_BUDGET',
                    'fetched_at': reference.isoformat(), 'expires_at': reference.isoformat()}
        else:
            state['requests'] += 1
            try:
                text, final_url = _body(adapter, candidate)
                item = {'signature': signature, 'status': 'SUCCESS', 'text': text,
                        'url': final_url, 'fetched_at': reference.isoformat(),
                        'expires_at': (reference + CACHE_AGE).isoformat()}
            except SourceFailure as error:
                if error.kind in ('ROBOTS_UNAVAILABLE', 'TLS_ERROR', 'DNS', 'TIMEOUT',
                                  'NETWORK', 'RATE_LIMIT', 'BLOCKED', 'HTTP'):
                    state['blocked_hosts'].add(host)
                item = {'signature': signature, 'status': 'FAILED',
                        'failure': error.record(stage='DETAIL_ENRICHMENT', url=candidate.official_detail_url),
                        'fetched_at': reference.isoformat(),
                        'expires_at': (reference + FAILURE_AGE).isoformat()}
    if item.get('status') == 'SUCCESS':
        item['recruitment_closed'] = bool(explicit_closure(program.title, item.get('text') or ''))
    candidate.raw_metadata[CACHE_KEY] = item
    return apply_evidence(program, item), item.get('text'), {
        'status': item['status'], 'cache_hit': cache_hit, 'failure': item.get('failure')}
