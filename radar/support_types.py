"""Canonical support categories; source payloads retain the original labels."""
from enum import StrEnum


class SupportType(StrEnum):
    GRANT='GRANT'
    COMPETITION='COMPETITION'
    INCUBATION='INCUBATION'
    ACCELERATION='ACCELERATION'
    INVESTMENT_LINKED='INVESTMENT_LINKED'
    WORKSPACE='WORKSPACE'
    GLOBAL='GLOBAL'
    MARKET_ENTRY='MARKET_ENTRY'
    EDUCATION='EDUCATION'
    MENTORING='MENTORING'
    CONSULTING='CONSULTING'
    POLICY_LOAN='POLICY_LOAN'
    SME_FINANCING='SME_FINANCING'
    GENERIC_RD='GENERIC_RD'
    UNKNOWN='UNKNOWN'


LABELS={
    'GRANT':'사업화 지원','COMPETITION':'경진대회','INCUBATION':'보육',
    'ACCELERATION':'액셀러레이팅','INVESTMENT_LINKED':'투자 연계','WORKSPACE':'공간 지원',
    'GLOBAL':'해외 진출','MARKET_ENTRY':'판로 지원','EDUCATION':'교육',
    'MENTORING':'멘토링','CONSULTING':'컨설팅','POLICY_LOAN':'정책 융자',
    'SME_FINANCING':'중소기업 금융','GENERIC_RD':'연구개발','UNKNOWN':'분류 미확인',
}
# Exact mappings only. Broad source categories are not inferred as cash grants.
RAW_MAPPING={
    '사업화':['GRANT'],'시설ㆍ공간ㆍ보육':['WORKSPACE','INCUBATION'],
    '멘토링ㆍ컨설팅ㆍ교육':['MENTORING','CONSULTING','EDUCATION'],
    '글로벌':['GLOBAL'],'수출':['GLOBAL'],'판로ㆍ해외진출':['MARKET_ENTRY','GLOBAL'],
    '기술개발(R&D)':['GENERIC_RD'],'융자':['POLICY_LOAN'],
}


def contract():
    return {'version':1,'types':[{'value':t.value,'label':LABELS[t.value]} for t in SupportType],
            'raw_mapping':RAW_MAPPING}


def normalize(values):
    result=[]
    for value in values:
        for item in ([value] if value in SupportType._value2member_map_ else RAW_MAPPING.get(value,['UNKNOWN'])):
            if item not in result:result.append(item)
    return result or ['UNKNOWN']
