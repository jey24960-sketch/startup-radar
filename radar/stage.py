"""GFC Stage Fit v1.0 — which startup stage benefits most from an opportunity?

Editorial metadata for scanning, not a publication gate and not eligibility.
"Who would benefit" is a different question from "who may apply": a programme
that helps a student founder incorporate is early-stage even though the word
법인 appears, and a programme that *requires* a corporation carries that as a
restriction, not as its stage. To keep the two apart structurally, late-stage
(STAGE_4) rules are never evaluated against the applicant summary, which is
where eligibility conditions live.

Deterministic rules, no AI, consistent with the rest of the weekly path. An
opportunity may fit one or two stages. When the evidence does not name an
activity or output, the result is an empty set, never an invented label.
"""
import re

STAGE_VERSION = 'gfc-stage-v1.0'
METHOD = 'DETERMINISTIC_RULES_V1'

# Exactly the five member-facing stages, in order. Codes are internal.
STAGES = (
    ('STAGE_0', '아이디어 전'),
    ('STAGE_1', '팀 구성·아이디어'),
    ('STAGE_2', '랜딩·시장검증'),
    ('STAGE_3', 'MVP·PoC'),
    ('STAGE_4', '사업자·법인 이후'),
)
LABELS = dict(STAGES)
ORDER = {code: index for index, (code, _) in enumerate(STAGES)}
MAX_STAGES = 2

TITLE_CHARS, APPLICANT_CHARS, SUPPORT_CHARS = 200, 500, 400


def _rules(pairs):
    return tuple((label, re.compile(pattern, re.I)) for label, pattern in pairs)


# Signals describe the activity a programme runs or the output it produces.
# Audience words (대학생, 청년, 스타트업, 창업기업, 중소기업, AI, 글로벌) are not here.
SIGNALS = {
    'STAGE_0': _rules([
        ('창업 입문·문제 발굴', r'창업\s*입문|창업\s*기초|문제\s*(발굴|정의|탐색)|아이디어\s*발굴|창업\s*(마인드|이해)|기업가\s*정신\s*(교육|캠프|부트캠프)|창업\s*(캠프|부트캠프)|창업\s*교육\s*(과정|프로그램)|창업\s*첫\s*걸음|예비\s*창업\s*교육'),
    ]),
    'STAGE_1': _rules([
        ('팀빌딩·아이디어톤', r'팀\s*빌딩|팀\s*구성|아이디어톤|해커톤|아이디어\s*(고도화|경진|공모|구체화|검증)|창업\s*아이디어|창업팀\s*(모집|선발|구성)'),
        ('예비창업자 프로그램', r'예비\s*창업(자|팀|패키지)|창업\s*준비|창업\s*동아리|창업\s*(경진대회|공모전|대회|챌린지)'),
    ]),
    'STAGE_2': _rules([
        ('고객·시장 검증', r'고객\s*(발굴|검증|인터뷰|확보)|시장\s*검증|수요\s*(검증|조사|테스트)|\bBM\b\s*검증|비즈니스\s*모델\s*(검증|개발|수립)|랜딩\s*페이지|초기\s*(고객|사용자)|사용자\s*테스트|PMF|린\s*스타트업|문제\s*해결\s*검증'),
    ]),
    'STAGE_3': _rules([
        ('MVP·프로토타입·PoC', r'\bMVP\b|프로토타입|시제품|시작품|제품\s*(개발|제작|고도화)|\bPoC\b|실증|파일럿|테스트\s*베드|리빙\s*랩|기술\s*검증|기술\s*(개발|고도화)\s*지원'),
        ('초기 사업화·보육', r'초기\s*사업화|사업화\s*(지원|연계)|기술\s*(이전|사업화|실용화)|창업\s*보육|보육\s*센터|입주|창업\s*공간|사업장\s*주소지|법인\s*설립[^\n]{0,12}(지원|대행|제공|컨설팅|안내)|사업자\s*등록[^\n]{0,10}(지원|대행)|초기\s*창업(자|기업|패키지)|액셀러레이[팅터]|배치\s*(프로그램|모집|선발)|accelerat|인큐베이[팅션]|레지던시|residency|초기\s*IR|\bIR\s*(교육|코칭|피칭\s*스킬)'),
    ]),
    'STAGE_4': _rules([
        ('오픈이노베이션·기업협업', r'오픈\s*이노베이션|open\s*innovation|대\-?중견\s*(기업\s*)?(연계|협업|매칭)|기업\s*협업\s*프로젝트|수요\s*기업\s*매칭|공동\s*사업화'),
        ('투자유치·IR', r'투자\s*(유치|매칭|연계|설명회|상담회)|\bVC\b|벤처\s*캐피탈|데모\s*데이|demo\s*day|investor\s*day|투자자\s*(매칭|미팅)|시리즈\s*[A-C]|\bPre-?\s*A\b|팁스|\bTIPS\b|후속\s*투자'),
        ('사업화 자금·스케일업', r'사업화\s*자금|스케일\s*업|scale-?up|성장\s*(지원|단계|자금)|도약\s*(패키지|지원)|매출\s*(확대|성장)|양산'),
        ('해외 진출·수출', r'해외\s*(진출|실증|파트너|법인|현지화|판로|전시|박람회)|글로벌\s*(진출|실증|파트너|액셀러|스케일)|(일본|미국|베트남|유럽|중국|동남아|인도|싱가포르|독일|영국|대만)\s*(시장\s*)?진출|수출\s*(지원|기업|바우처|계약)|바이어\s*(매칭|상담|발굴)|현지\s*(진출|파트너|투자자)|(국제|글로벌|아시아|해외)[^\n]{0,12}(전시회|박람회|엑스포|expo)|통합관|파빌리온'),
    ]),
}


def _text_for(stage, facts):
    title = str(facts.get('title') or '')[:TITLE_CHARS]
    support = str(facts.get('support_summary') or '')[:SUPPORT_CHARS]
    applicant = str(facts.get('applicant_summary') or '')[:APPLICANT_CHARS]
    # Eligibility text may say "법인사업자만" or "매출 10억 이상": those are
    # restrictions on who may apply, not evidence of who benefits, so late-stage
    # signals are read from the programme's own description only.
    if stage == 'STAGE_4':
        return '\n'.join(p for p in (title, support) if p)
    return '\n'.join(p for p in (title, applicant, support) if p)


def classify_stage(facts):
    """Return the stage decision for one stored editorial snapshot."""
    evidence, counts = {}, {}
    for code, _ in STAGES:
        text = _text_for(code, facts)
        hits = []
        for label, pattern in SIGNALS[code]:
            hits += [{'rule': label, 'match': m.group(0)[:60]} for m in pattern.finditer(text)]
        if hits:
            # Rank by total signal count; keep a bounded evidence sample for audit.
            counts[code] = len(hits)
            evidence[code] = hits[:6]
    if not counts:
        return _decision([], '근거 부족: 단계 미판정', evidence)
    ranked = sorted(counts, key=lambda code: (-counts[code], ORDER[code]))
    codes = sorted(ranked[:MAX_STAGES], key=ORDER.__getitem__)
    reason = ' · '.join(dict.fromkeys(hit['rule'] for code in codes for hit in evidence[code]))[:200]
    return _decision(codes, reason, {'counts': counts, 'matches': evidence})


def _decision(codes, reason, evidence):
    return {'stage_codes': list(codes), 'stage_labels': [LABELS[c] for c in codes],
            'stage_version': STAGE_VERSION, 'method': METHOD, 'reason': reason, 'evidence': evidence}


def labels_for(codes):
    """Member-facing labels for stored codes; unknown codes are dropped, never invented."""
    return [LABELS[c] for c in (codes or []) if c in LABELS]


def telegram_tag(codes):
    """`[MVP·PoC]` or `[MVP·PoC / 사업자·법인 이후]`; empty string when unresolved."""
    labels = labels_for(codes)
    return f"[{' / '.join(labels)}]" if labels else ''
