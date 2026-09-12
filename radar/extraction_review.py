"""Conservative checks for meanings the current flat profile model cannot encode.

These checks can withdraw certainty, never create eligibility or new restrictions.
They are not a complete natural-language interpretation engine.
"""
import re


def rule_review_reasons(rule):
    quotes='\n'.join(e.text for e in rule.evidence if e.verified)
    reasons=[]
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
    return reasons


def future_commitments(evidence):
    findings=[]
    for key,text in evidence.items():
        for line in text.splitlines():
            if (re.search(r'(?:입주|선정|협약)\s*후',line)
                and re.search(r'사업자\s*등록|주소(?:지)?\s*이전|소재지.*이전',line)
                and re.search(r'가능|필수|해야|하여야|해야만',line)):
                findings.append({'kind':'FUTURE_COMMITMENT_NOT_REPRESENTED','evidence_key':key,'quote':line.strip()[:500]})
    return findings
