"""GFC Relevance v1.1 — is this opportunity useful to a GFC founder?

Deterministic rules only. The weekly production path intentionally does not
depend on AI, OCR or eligibility calculation, and that reliability property is
worth more than marginal recall here: a classifier that can time out or
hallucinate eligibility would put the single weekly publication at risk. Every
decision below is reproducible from stored facts and carries its matched
evidence, so an operator can audit exactly why an item was shown or hidden.

Two axes, in order (see docs/WEEKLY-BRIEFING.md):

  AXIS A  startup leverage      HIGH | LOW
  AXIS B  applicability          BROAD | RESTRICTED   (only evaluated when HIGH)

  HIGH + BROAD      -> GFC_RELEVANT
  HIGH + RESTRICTED -> CONDITIONAL
  LOW               -> OUT_OF_SCOPE
  conflicting/thin  -> REVIEW_REQUIRED  (operational state, never shown to members)

Audience words alone are never evidence. "중소기업", "소상공인", "스타트업",
"창업벤처", "청년", "대학생", "AI", "글로벌" describe who may apply, not what the
program lets a founder do, so none of them appear as a leverage signal below.
What counts is the action the program enables and the deliverable it produces.
"""
import re

RELEVANCE_VERSION = 'gfc-v1.1'
CLASSIFICATION_METHOD = 'DETERMINISTIC_RULES_V1_1'

GFC_RELEVANT = 'GFC_RELEVANT'
CONDITIONAL = 'CONDITIONAL'
OUT_OF_SCOPE = 'OUT_OF_SCOPE'
REVIEW_REQUIRED = 'REVIEW_REQUIRED'

# Only these two are ever rendered to members.
PUBLISHABLE_STATUSES = (GFC_RELEVANT, CONDITIONAL)

_MIN_EVIDENCE_TEXT = 80


def _rules(pairs):
    return tuple((label, re.compile(pattern, re.I)) for label, pattern in pairs)


# ---------------------------------------------------------------------------
# AXIS A — leverage
# ---------------------------------------------------------------------------

# Absolute exclusions. These describe the substantive purpose of the program,
# not an incidental mention, and they win over every other signal.
HARD_EXCLUSION = _rules([
    ('착한가격업소', r'착한가격(업소)?'),
    ('카드·결제 수수료 지원', r'(카드|결제|가맹점)\s*수수료'),
    ('소상공인 경영비용 지원', r'소상공인[^\n]{0,20}(경영\s*(안정|개선|회복)|버팀목|보조금|지원금|융자)'),
    ('경영안정·운전자금', r'경영\s*(안정|개선)\s*자금|운전자금|긴급\s*경영'),
    ('임차료·공과금 보전', r'(임차료|임대료|전기\s*요금|공과금|관리비)\s*(지원|보전|감면)'),
    ('신용보증·보증료 지원', r'(특례\s*)?신용\s*보증|보증료\s*(지원|감면)'),
    ('물류·운송비 보전', r'(물류비|운송비|배송비|택배비)\s*(지원|보전)'),
    ('고용장려·인건비 지원', r'고용\s*(장려금|유지)|인건비\s*지원|채용\s*지원금|일자리\s*장려'),
    ('채용·인턴 모집', r'(신입|경력)?\s*(사원|직원|연구원)\s*채용|인턴(십|사원)?\s*모집|체험형\s*인턴|인턴\s*모집|서포터즈\s*모집|아르바이트'),
    ('가족친화·근로자 복지 인증', r'가족친화\s*인증|근로자\s*복지|복지\s*포인트'),
    ('직무발명보상 인증', r'직무\s*발명\s*보상'),
    ('표창·포상·시상', r'표창|포상|유공자|시상식|수상\s*기업\s*선정'),
    ('안전·위생·규제 준수', r'안전보건|중대재해|산업안전|위생\s*관리|소방\s*(점검|안전)'),
    ('제조공정·설비 고도화', r'스마트\s*공장|뿌리\s*(기업|산업|기술)|공정\s*(개선|혁신|연구)|생산\s*설비|제조\s*공정|자동화\s*설비'),
    # Incumbent-manufacturer upgrades read as innovation but are operating support
    # for established factories, and they often mention 실증/사업화 in passing.
    ('부품 국산화·제조 DX', r'국산화|제조\s*(디지털\s*전환|디지털전환|\bDX\b)'),
    ('보험료·부담금 보전', r'(보험료|부담금|수수료)\s*(지원|보전|감면)|책임보험'),
    ('사업재편·구조조정', r'사업\s*(재편|전환)\s*(지원|컨설팅)?|산업\s*위기|구조\s*조정|전환\s*성장'),
    ('직판·행사 판매 참여', r'장터|푸드\s*트럭|팝업\s*스토어|기획\s*판매전|직거래|플리마켓|동행\s*축제'),
    ('사회적경제·공공구매', r'사회적\s*경제|사회연대\s*경제|공공\s*구매|마을\s*기업|협동조합\s*지원'),
])

# Plausible-but-usually-generic categories. Hidden unless a core startup signal
# shows the program actually advances a founder's execution.
GENERIC_SOFT_EXCLUSION = _rules([
    ('일반 판로·전시 참가 지원', r'판로\s*(개척|지원)|전시회\s*참가|박람회\s*참가|시장\s*개척단|무역\s*사절단|수출\s*바우처|해외\s*규격\s*인증'),
    ('일반 인증·컨설팅 지원', r'(규격|시험|성적서|경영|품질)\s*인증|인증\s*획득|일반\s*컨설팅|경영\s*컨설팅'),
    ('일반 교육 과정', r'교육생\s*모집|직무\s*교육|장비\s*교육|역량\s*강화\s*교육|아카데미\s*수강'),
])

# Talks, briefings and networking. Hidden unless the program produces a concrete
# founder deliverable, which is a deliberately narrower bar than the core list.
EVENT_SOFT_EXCLUSION = _rules([
    ('일회성 강연·행사', r'특강|강연|세미나|설명회|간담회|컨퍼런스|포럼|네트워킹|밋업|커피챗|토크\s*콘서트'),
    ('사례·후기 공유', r'성공\s*(사례|스토리)|후기|이야기|경험\s*공유'),
])

# AXIS A positives: what the founder actually gets to do.
CORE_STARTUP = _rules([
    ('액셀러레이팅·배치 선발', r'액셀러레이[팅터]|엑셀러레이[팅터]|배치\s*(프로그램|모집|선발)|\bbatch\b|accelerat|인큐베이[팅션]|레지던시|residency'),
    ('창업 보육·입주 공간', r'창업\s*보육|보육\s*센터|입주\s*(기업|팀|기업체|공간|모집|신청)|창업\s*공간|메이커\s*스페이스'),
    # English is common in Korean startup programme titles ("INVESTOR DAY"),
    # so the investor track must match both languages.
    ('투자 매칭·IR·데모데이', r'\bIR\b|데모\s*데이|demo\s*day|investor\s*day|pitch(ing)?\s*day|투자\s*(매칭|연계|유치\s*지원|설명회|상담회)|피칭|피치\s*덱|투자자\s*매칭|쇼케이스'),
    ('MVP·프로토타입 제작', r'\bMVP\b|프로토타입|시제품|시작품|제품\s*개발\s*지원'),
    ('실증·PoC·테스트베드', r'\bPoC\b|실증|테스트\s*베드|리빙\s*랩'),
    ('오픈이노베이션 협업', r'오픈\s*이노베이션|open\s*innovation|대\-?중견\s*연계|수요\s*기업\s*매칭'),
    ('사업화·상용화 지원', r'사업화\s*(지원|자금|연계)|제품화|상용화'),
    ('창업 경진대회·공모전', r'창업\s*(경진대회|공모전|대회|챌린지)|스타트업\s*(경진대회|공모전|챌린지)|아이디어\s*공모'),
    ('예비·초기 창업자 선발', r'예비\s*창업(자|팀|패키지)|초기\s*창업(자|패키지)|창업\s*도약|재도전\s*창업|청년\s*창업\s*사관'),
    ('기술이전·기술사업화', r'기술\s*(이전|사업화)|기술\s*실용화'),
    ('글로벌 진출 실행', r'(글로벌|해외|국제|현지)[^\n]{0,20}(진출|실증|파트너|바이어\s*매칭|투자자|액셀러|법인\s*설립)|(스타트업|창업\s*기업)[^\n]{0,15}(통합관|파빌리온|공동관)'),
    ('창업 특화 법률·지분·IP', r'(창업|스타트업|투자)\s*(법률|계약|지분|주주간|특허|IP)|주주간\s*계약|지분\s*구조|투자\s*계약|스톡옵션'),
])

# The stricter subset able to rescue a talk/event: it must leave the founder
# with something concrete.
DELIVERABLE = _rules([
    ('MVP·프로토타입 결과물', r'\bMVP\b|프로토타입|시제품|시작품'),
    ('실증·PoC 수행', r'\bPoC\b|실증|테스트\s*베드'),
    ('IR·데모데이 선발', r'데모\s*데이|demo\s*day|\bIR\s*(피칭|덱|자료|발표)|투자\s*(매칭|연계)'),
    ('액셀러레이팅 선발', r'액셀러레이[팅터]|배치\s*(프로그램|선발)|accelerat'),
    ('사업화·상용화 지원', r'사업화\s*(지원|자금)|상용화'),
    ('고객·시장 검증 수행', r'고객\s*(발굴|검증|인터뷰)|시장\s*검증|\bBM\b\s*검증|비즈니스\s*모델\s*검증'),
])


# ---------------------------------------------------------------------------
# AXIS B — applicability
# ---------------------------------------------------------------------------

RESTRICTION = _rules([
    ('특정 산업 분야 한정', r'바이오|헬스\s*케어|의료\s*기기|제약|반도체|이차\s*전지|배터리|소재\s*부품\s*장비|디스플레이|조선|자동차\s*부품|방위\s*산업|우주\s*항공|농업|수산|축산|식품\s*산업|화학\s*산업|섬유|뿌리\s*산업|관광|콘텐츠\s*산업'),
    ('사업자등록·법인 필요', r'사업자\s*등록(증|자)?\s*(보유|필수|필요|기업)|법인\s*(설립|사업자)\s*(필수|필요|보유)|중소기업\s*확인서'),
    ('투자 단계 한정', r'\bPre-?\s*A\b|\bSeries\s*[A-C]\b|시리즈\s*[A-C]|프리\s*에이'),
    # Only a *minimum maturity* requirement restricts GFC members. An
    # "early-stage only" window (창업 3년 이내) is the audience, not a barrier,
    # and treating it as one would push most real accelerators into CONDITIONAL.
    ('업력 하한 조건', r'(?:업력|설립|창업)\s*\d+\s*년\s*이상'),
    ('수출 실적 요건', r'수출\s*실적|수출\s*\d+\s*(만|억)'),
    ('소재지 이전 필요', r'(본사|기업)\s*이전|이전\s*조건|관내\s*이전'),
])

# A bracketed regional prefix is how the national portals mark a locally scoped
# program; "소재" is the explicit textual form.
_REGION_PREFIX = re.compile(r'^\s*[\[【]\s*([가-힣]{2,8}(?:\s*[·ㆍ]\s*[가-힣]{2,8})?)\s*[\]】]')
# Korean notices attach particles freely ("충청남도에 소재한", "서울시 소재 기업"),
# so the administrative noun is anchored and the particle is optional.
_REGION_TEXT = re.compile(r'([가-힣]{2,6}(?:특별자치[시도]|특별시|광역시|[가-힣]도|[가-힣]시|[가-힣]군|[가-힣]구))\s*(?:에|내|의)?\s*소재')
_REGION_LOCAL = re.compile(r'관내\s*(?:에\s*)?소재|관내\s*(?:기업|업체|법인)')


# Bounded, so the decision is reproducible and cheap. The substantive purpose of
# a Korean public notice is stated in its title and opening summary; eligibility
# restrictions live in the applicant summary, which therefore gets more room.
APPLICANT_EVIDENCE_CHARS = 500
SUPPORT_EVIDENCE_CHARS = 400


def _text(facts):
    parts = [str(facts.get('title') or ''),
             str(facts.get('applicant_summary') or '')[:APPLICANT_EVIDENCE_CHARS],
             str(facts.get('support_summary') or '')[:SUPPORT_EVIDENCE_CHARS]]
    return '\n'.join(p for p in parts if p)


def _matches(rules, text):
    found = []
    for label, pattern in rules:
        hit = pattern.search(text)
        if hit:
            found.append({'label': label, 'match': hit.group(0)[:80]})
    return found


def _restrictions(facts, text):
    found = _matches(RESTRICTION, text)
    title = str(facts.get('title') or '')
    region = _REGION_PREFIX.search(title)
    if region:
        found.append({'label': '지역 한정', 'match': region.group(1), 'summary': f'{region.group(1)} 지역 사업'})
    else:
        region = _REGION_TEXT.search(text)
        if region:
            found.append({'label': '지역 한정', 'match': region.group(0)[:40], 'summary': f'{region.group(1)} 소재 기업'})
        elif _REGION_LOCAL.search(text):
            found.append({'label': '지역 한정', 'match': _REGION_LOCAL.search(text).group(0)[:40],
                          'summary': '주관기관 관내 소재 기업'})
    return found


def _restriction_summary(found):
    labels = []
    for item in found:
        label = item.get('summary') or item['label']
        if label not in labels:
            labels.append(label)
    return ' · '.join(labels)[:200] or None


def classify(facts):
    """Classify one stored editorial snapshot. Never mutates source facts."""
    text = _text(facts)
    hard = _matches(HARD_EXCLUSION, text)
    core = _matches(CORE_STARTUP, text)
    evidence = {'hard_exclusion': hard, 'core_startup': core}

    if hard and core:
        # A real conflict: a founder-facing action inside an excluded program
        # type. Do not guess either way.
        return _decision(REVIEW_REQUIRED, 'UNKNOWN', 'UNKNOWN', '상충 신호: 운영자 확인 필요',
                         None, dict(evidence, conflict=True))
    if hard:
        return _decision(OUT_OF_SCOPE, 'LOW', 'UNKNOWN', hard[0]['label'], None, evidence)

    generic = _matches(GENERIC_SOFT_EXCLUSION, text)
    event = _matches(EVENT_SOFT_EXCLUSION, text)
    deliverable = _matches(DELIVERABLE, text)
    evidence.update(generic_soft=generic, event_soft=event, deliverable=deliverable)

    if event and not deliverable:
        return _decision(OUT_OF_SCOPE, 'LOW', 'UNKNOWN', event[0]['label'], None, evidence)
    if generic and not core:
        return _decision(OUT_OF_SCOPE, 'LOW', 'UNKNOWN', generic[0]['label'], None, evidence)

    if not core:
        if len(text.strip()) < _MIN_EVIDENCE_TEXT:
            return _decision(REVIEW_REQUIRED, 'UNKNOWN', 'UNKNOWN', '근거 텍스트 부족: 운영자 확인 필요',
                             None, dict(evidence, thin_text=True))
        return _decision(OUT_OF_SCOPE, 'LOW', 'UNKNOWN', '창업 실행 레버리지 근거 없음', None, evidence)

    restrictions = _restrictions(facts, text)
    evidence['restriction'] = restrictions
    reason = ' · '.join(dict.fromkeys(item['label'] for item in core))[:200]
    if restrictions:
        return _decision(CONDITIONAL, 'HIGH', 'RESTRICTED', reason,
                         _restriction_summary(restrictions), evidence)
    return _decision(GFC_RELEVANT, 'HIGH', 'BROAD', reason, None, evidence)


def _decision(status, leverage, applicability, reason, restriction, evidence):
    return {'relevance_status': status, 'relevance_version': RELEVANCE_VERSION,
            'startup_leverage': leverage, 'applicability': applicability,
            'startup_leverage_reason': reason,
            'restriction_summary': restriction,
            'classification_method': CLASSIFICATION_METHOD,
            'evidence': evidence}
