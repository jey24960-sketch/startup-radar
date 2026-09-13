import json
from types import SimpleNamespace
import pytest
from radar.adapters.official import KStartupApiAdapter
from radar.adapters.base import SourceFailure

def test_supplement_survives_latest_page_cap_and_deduplicates(monkeypatch):
    monkeypatch.setenv('KSTARTUP_API_KEY','test')
    calls=[]
    def get(url,params):
        calls.append(params)
        ids=[1,2] if 'cond[biz_pbanc_nm::LIKE]' not in params else [2,3]
        rows=[{'pbanc_sn':i,'biz_pbanc_nm':str(i),'biz_aply_url':f'https://example.org/{i}'} for i in ids]
        return json.dumps({'data':rows,'matchCount':100 if len(calls)==1 else 2}).encode(),'application/json',url
    source={'slug':'kstartup','config':{'page_size':2,'max_pages':1,'current_title_queries':['Current','Current']}}
    iterator=KStartupApiAdapter(source,SimpleNamespace(get=get)).discover();rows=[]
    with pytest.raises(SourceFailure,match='PAGE_LIMIT'):
        while True:rows.append(next(iterator))
    assert [r.source_program_id for r in rows]==['1','2','3']
    assert len(calls)==2
    assert calls[1]['cond[rcrt_prgs_yn::EQ]']=='Y'

@pytest.mark.parametrize('queries',[['x']*6,[''],[None],'Current'])
def test_invalid_query_configuration_fails_before_http(monkeypatch,queries):
    monkeypatch.setenv('KSTARTUP_API_KEY','test')
    source={'slug':'kstartup','config':{'current_title_queries':queries}}
    with pytest.raises(SourceFailure,match='CONFIGURATION'):
        list(KStartupApiAdapter(source,None).discover())

def test_supplement_api_error_is_not_empty_success(monkeypatch):
    monkeypatch.setenv('KSTARTUP_API_KEY','test')
    def get(url,params):
        data={'error':'denied'} if 'cond[biz_pbanc_nm::LIKE]' in params else {'data':[]}
        return json.dumps(data).encode(),'application/json',url
    source={'slug':'kstartup','config':{'current_title_queries':['Current']}}
    with pytest.raises(SourceFailure,match='API_SCHEMA'):
        list(KStartupApiAdapter(source,SimpleNamespace(get=get)).discover())
