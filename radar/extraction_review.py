"""Conservative checks for meanings the current flat profile model cannot encode.

These checks can withdraw certainty, never create eligibility or new restrictions.
They are not a complete natural-language interpretation engine.
"""
import re


def rule_review_reasons(rule):
    quotes='\n'.join(e.text for e in rule.evidence if e.verified)
    reasons=[]
    if rule.key=='region' and re.search(r'본사|본점|공장|지사|지점',quotes):
        # TeamProfile.region has no facility type or multiple-location semantics.
        # A literal region quote cannot prove which establishment is located there.
        reasons.append('FACILITY_LOCATION_NOT_REPRESENTED')
    if rule.key=='business_status' and rule.operator!='EXISTS':
        patterns={'PRE_BUSINESS':r'예비\s*창업',
                  'SOLE_PROPRIETOR':r'개인\s*사업자|기\s*창업자|사업자\s*등록',
                  'CORPORATION':r'법인|기\s*창업자|사업자\s*등록'}
        values=rule.value if isinstance(rule.value,list) else [rule.value]
        if any(not re.search(patterns[value],quotes) for value in values):
            reasons.append('BUSINESS_STATUS_NOT_EXPLICIT')
    if rule.key=='prior_support_restrictions':
        # User-entered free text is not a controlled declaration of tax, credit,
        # industry, sanctions or every possible prior award/exclusion condition.
        reasons.append('UNCONTROLLED_HISTORY_VALUES')
    if rule.key=='business_age_months':
        if re.search(r'예비\s*창업',quotes):reasons.append('BUSINESS_AGE_BRANCH_NOT_REPRESENTED')
        if re.search(r'공고일|공고\s*일|모집\s*공고.*기준',quotes):reasons.append('BUSINESS_AGE_REFERENCE_DATE_NOT_REPRESENTED')
    if rule.key=='student_status' and re.search(r'휴학|졸업',quotes):
        reasons.append('STUDENT_ALTERNATIVES_NOT_REPRESENTED')
    return reasons


def rule_context_reasons(rule,evidence):
    if not rule.mandatory:return []
    compact=lambda text:re.sub(r'\s+',' ',text).strip()
    for item in rule.evidence:
        if not item.verified:continue
        source=compact(evidence.get(item.document_id or item.source_id,''));quote=compact(item.text)
        if not quote:continue
        start=source.find(quote)
        if start<0:continue
        context=source[max(0,start-140):start+len(quote)]
        if re.search(r'동\s*순위|우대\s*(?:사항|조건|대상)|가점\s*(?:항목|사항|대상)|우선\s*선정',context):
            return ['PREFERENCE_NOT_MANDATORY']
        if rule.key=='product_stage' and '개발단계' in context and re.search(r'□|☐',context):
            return ['FORM_OPTION_NOT_REQUIREMENT']
    return []


def omitted_applicant_conditions(evidence,requirements,applicant_summary,eligibility_quote):
    """Review grounded applicant passages independently of emitted rule keys.

    Deliberately bounded: this is not a guarantee that every omitted condition is
    detected. Titles, benefit paragraphs and ungrounded model quotes cannot flag
    an enterprise restriction. Never synthesize a business-status requirement.
    """
    business_represented=any(r.key=='business_status' and r.mandatory and r.certain for r in requirements)
    compact=lambda text:re.sub(r'\s+',' ',text).strip()
    sources=[compact(text) for text in evidence.values()]
    quotes=[]
    for passage in (applicant_summary,eligibility_quote):
        text=compact(passage or '')
        if not text or not any(text in source for source in sources):continue
        # Explicit establishment-based enterprise qualification, seen in actual
        # procurement notices. Do not infer this from the general word 기업.
        if re.search(r'(?:본사|본점|공장).{0,100}소재.{0,100}기업',text):
            if text not in quotes:quotes.append(text[:500])
    if not quotes:return []
    findings=[{'kind':'FACILITY_LOCATION_NOT_REPRESENTED','requirement_key':'region','quotes':quotes}]
    if not business_represented:
        findings.append({'kind':'BUSINESS_STATUS_NOT_EXPLICIT','requirement_key':'business_status','quotes':quotes})
    return findings


def future_commitments(evidence):
    findings=[]
    for key,text in evidence.items():
        for line in text.splitlines():
            if (re.search(r'(?:입주|선정|협약)\s*후',line)
                and re.search(r'사업자\s*등록|주소(?:지)?\s*이전|소재지.*이전',line)
                and re.search(r'가능|필수|해야|하여야|해야만|예정',line)):
                findings.append({'kind':'FUTURE_COMMITMENT_NOT_REPRESENTED','evidence_key':key,'quote':line.strip()[:500]})
    return findings
