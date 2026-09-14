"""Conservative source facts, not an eligibility or investment promise."""
import re
from datetime import datetime
from urllib.parse import urlsplit, urljoin
from pydantic import BaseModel, ConfigDict, Field, field_validator
from core.clock import SEOUL
from radar.identity import digest, normalize_text, normalize_url

ORGANIZATION_TYPES = ('GOVERNMENT','PUBLIC_INSTITUTION','VC','AC','CVC','FOUNDATION','UNIVERSITY','CORPORATE','OTHER','UNKNOWN')
CATEGORIES = ('PUBLIC_SUPPORT','COMPETITION','ACCELERATOR','OPEN_INNOVATION','EDUCATION_SPACE','EVENT','INVESTMENT_REVIEW','OTHER')
PARTICIPATION = ('TEAM_RECRUITMENT','EVENT_ATTENDANCE','INVESTMENT_APPLICATION','UNKNOWN')


class OpportunityFacts(BaseModel):
    model_config = ConfigDict(extra='forbid')
    organization_type: str = 'UNKNOWN'
    category: str = 'OTHER'
    participation: str = 'UNKNOWN'
    cohort: str | None = None
    year: int | None = None
    stages: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    event_start_at: str | None = None
    event_end_at: str | None = None
    fee: str | None = None
    investment_terms: str | None = None
    benefit_kind: str = 'UNKNOWN'
    cancelled: bool = False
    recruitment_confirmed: bool = False
    application_link_verified: bool = False
    evidence: dict = Field(default_factory=dict)
    review_reasons: list[str] = Field(default_factory=list)

    @field_validator('organization_type','category','participation')
    @classmethod
    def known_classification(cls,value,info):
        allowed={'organization_type':ORGANIZATION_TYPES,'category':CATEGORIES,'participation':PARTICIPATION}
        if value not in allowed[info.field_name]:raise ValueError('Unknown classification')
        return value


EXCLUDED_TITLE = re.compile(r'채용|합격자|최종\s*선정|선정\s*결과|결과\s*발표|선발\s*결과|수상\s*결과|투자\s*유치\s*(?:성공|완료)|보도자료|행사\s*후기|인턴\s*모집|경품|도록\s*발간')
RECRUITMENT = re.compile(r'모집|접수|참가\s*신청|참여\s*신청|입주\s*신청|지원\s*신청|applications?\s+(?:are\s+)?(?:open|accepted)|apply\s+now', re.I)
DATE = r'(?P<y>20\d{2})\s*[.년/-]\s*(?P<m>\d{1,2})\s*[.월/-]\s*(?P<d>\d{1,2})\s*일?\.?'


def explicit_date(value, end=False):
    match = re.search(DATE, value or '')
    if not match: return None, 'UNKNOWN'
    tail = value[match.end():]
    clock = re.match(r'\s*(?:\([^)]{1,5}\))?\s*(\d{1,2}):([0-5]\d)', tail)
    try:
        dt = datetime(int(match['y']),int(match['m']),int(match['d']),
                      int(clock[1]) if clock else 23 if end else 0,
                      int(clock[2]) if clock else 59 if end else 0,
                      0 if clock or not end else 59,tzinfo=SEOUL)
        return dt, 'DATETIME' if clock else 'DATE'
    except ValueError: return None, 'UNKNOWN'


def labeled_period(text,context_year=None):
    """Never interpret a general event date or a posting date as a deadline."""
    match = re.search(r'(?:모집\s*기간|신청\s*기간|접수\s*기간|지원\s*기간|서류\s*접수)\s*[)）:：]?\s*', text) or re.search(r'모집\s*일정\s*[)）:：]?\s*',text)
    if not match: return None,None,'UNKNOWN','UNKNOWN',None
    line=re.split(r'[○□■]|(?:행사|사업|운영)\s*기간',text[match.end():match.end()+200],maxsplit=1)[0]
    line=re.sub(r'\s+',' ',line).strip()
    if context_year and re.match(r'\d{1,2}\s*[.월/-]\s*\d{1,2}',line):line=f'{context_year}.'+line
    if not re.match(r'20\d{2}\s*[.년/-]',line):return None,None,'UNKNOWN','UNKNOWN',match[0]
    parts=re.split(r'\s*[~∼～]\s*',line,maxsplit=1)
    if len(parts)!=2:return None,None,'UNKNOWN','UNKNOWN',match[0]
    start,sp=explicit_date(parts[0]);end,ep=explicit_date(parts[1],True)
    # Inherit a year only inside one explicitly labelled range with a full start year.
    if start and end is None and not re.search(r'20\d{2}',parts[1]):
        short=re.match(r'(\d{1,2})\s*[.월/-]\s*(\d{1,2})(.*)',parts[1])
        if short:end,ep=explicit_date(f'{start.year}.{short[1]}.{short[2]}{short[3]}',True)
    if start and end and end<start:return None,None,'UNKNOWN','UNKNOWN',match[0]
    return start,end,sp,ep,match[0]+line[:160]


def classify(title,text,config):
    facts=OpportunityFacts(organization_type=config.get('organization_type','UNKNOWN'))
    def evidence(key,value):
        if value:facts.evidence[key]={'text':value[:500],'url':config.get('official_url')}
    if EXCLUDED_TITLE.search(title):
        facts.review_reasons.append('NOT_RECRUITMENT');return facts
    focus=title+'\n'+text[:2000]
    confirmed=RECRUITMENT.search(focus)
    facts.recruitment_confirmed=bool(confirmed)
    evidence('recruitment',confirmed.group(0) if confirmed else None)
    if re.search(r'참관|관객|청중|네트워킹|밋업|세미나|행사\s*참가|커피챗|Let.s Chat',title,re.I):
        facts.participation='EVENT_ATTENDANCE';facts.category='EVENT'
    elif re.search(r'투자\s*(?:검토|심사)|IR\s*(?:접수|제출)|investment\s*(?:review|application)',title,re.I):
        facts.participation='INVESTMENT_APPLICATION';facts.category='INVESTMENT_REVIEW'
    elif re.search(r'모집|경진대회|공모전|입주|배치|batch|residency|accelerat',title,re.I):
        facts.participation='TEAM_RECRUITMENT'
    if facts.category=='OTHER':
        for pattern,category in [(r'경진대회|공모전|창업대회|챌린지','COMPETITION'),(r'오픈\s*이노베이션|실증|협업|PoC','OPEN_INNOVATION'),
             (r'배치|batch|accelerat|액셀러|residency','ACCELERATOR'),(r'교육|입주|보육|공간|멘토링|창업동아리','EDUCATION_SPACE')]:
            if re.search(pattern,title,re.I):facts.category=category;break
    for key,pattern in [('cohort',r'(?:배치\s*|batch\s*)?\d+\s*기|제\s*\d+\s*회'),('year',r'20\d{2}')]:
        match=re.search(pattern,title,re.I)
        if match:setattr(facts,key,int(match[0]) if key=='year' else re.sub(r'\s+','',match[0]));evidence(key,match[0])
    for label,field in [('참가비|참여비|비용','fee'),('투자\s*조건|지분\s*조건|지분율','investment_terms')]:
        match=re.search(r'(?:'+label+r')\s*[:：]\s*([^\n]{1,250})',text)
        if match:setattr(facts,field,match[1]);evidence(field,match[0])
    for label,key in [('지원\s*대상|신청\s*대상|신청\s*자격|모집\s*대상','target'),('지역\s*제한|소재지','regions'),('업종\s*제한|모집\s*분야','industries')]:
        match=re.search(r'(?:'+label+r')\s*[)）:：]?\s*([^\n]{2,250})',text)
        if match:
            evidence(key,match[0])
            if key!='target':setattr(facts,key,[match[1]])
            else:
                for label in ('예비창업','학생','초기창업','창업 3년','창업 7년','스케일업'):
                    if label in match[1]:facts.stages.append(label)
    if re.search(r'모집\s*취소|사업\s*취소|접수\s*취소',title+'\n'+text[:500]):facts.cancelled=True
    for pattern,kind in [(r'선발\s*시.{0,20}투자','INVESTMENT_IF_SELECTED'),(r'투자\s*검토|투자\s*심사','INVESTMENT_REVIEW'),(r'상금','PRIZE'),(r'무상\s*지원금|사업화\s*지원금','GRANT')]:
        match=re.search(pattern,text)
        if match and re.search(r'아님|아니|제공하지|해당하지',text[match.end():match.end()+35].split('\n')[0]):continue
        if match:facts.benefit_kind=kind;evidence('benefit_kind',match[0]);break
    if not confirmed:facts.review_reasons.append('RECRUITMENT_UNCONFIRMED')
    if facts.participation=='UNKNOWN':facts.review_reasons.append('PARTICIPATION_UNKNOWN')
    return facts


def identity_scope(program):
    f=program.opportunity or {}
    return {key:f.get(key) for key in ('cohort','year','participation','regions')}


def strict_duplicate_key(program):
    f=program.opportunity or {}
    if not program.application_url or not f.get('application_link_verified') or not (f.get('cohort') or f.get('year')) or f.get('participation') in (None,'UNKNOWN'):
        return None
    return digest({'organization':normalize_text(program.organization),'title':normalize_text(program.title),
                   'scope':identity_scope(program),'apply':normalize_url(program.application_url),
                   'start':str(program.application_start_at)})
