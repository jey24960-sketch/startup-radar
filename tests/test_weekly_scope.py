from copy import deepcopy
import pytest
from radar.weekly_scope import POLICY,weekly_sources,source_completed,collection_completed
from radar.adapters.base import SourceFailure
from test_official_pagination import adapter,page


def capped_source():
    return {'status':'PARTIAL','discovered':20,'fetched':20,'parsed':20,
        'failures':[{'kind':'PAGE_LIMIT'}],
        'coverage':{'weekly_policy':POLICY,'scope':'OPEN','pagination_complete':False,
            'page_cap':1,'page_size':20,'persisted_records':20,'unique_source_ids':20,
            'failed_records':0,'rejected_records':0,
            'queries':[{'pagination_complete':False,'pages_requested':1,'unique_records':20}]}}


def test_weekly_configuration_is_bounded_without_mutating_registry():
    sources=[{'adapter':kind,'config':{'max_pages':100,'page_size':100,
        'allowed_hosts':['example.org'],'current_title_queries':['Existing featured notice']}}
        for kind in ('KSTARTUP','BIZINFO')]
    before=deepcopy(sources)
    configured=weekly_sources(sources)
    assert sources==before
    assert [s['config']['scope'] for s in configured]==['OPEN','API_DEFAULT']
    assert all(s['config']['max_pages']==1 and s['config']['page_size']==100
        and s['config']['weekly_policy']==POLICY for s in configured)
    assert configured[0]['config']['current_title_queries']==sources[0]['config']['current_title_queries']


def test_bounded_warning_is_not_full_coverage_and_requires_two_healthy_sources():
    source=capped_source()
    assert source_completed(source)
    assert collection_completed([source,source])
    assert not source['coverage']['pagination_complete']
    assert source['status']=='PARTIAL' and source['failures']==[{'kind':'PAGE_LIMIT'}]
    assert not collection_completed([source])
    assert not collection_completed([source,{'status':'FAILED'}])
    del source['coverage']['weekly_policy']
    assert not source_completed(source)
    assert source_completed(source,legacy=True)


@pytest.mark.parametrize('kind',['MISSING_CREDENTIAL','HTTP_401','NETWORK','API_JSON',
    'API_SCHEMA','PAGINATION_STALLED','PAGINATION_INCOMPLETE','NORMALIZE_OR_PERSIST'])
def test_real_failures_are_never_downgraded(kind):
    source=capped_source()
    source['failures'].append({'kind':kind})
    assert not source_completed(source) and not source_completed(source,legacy=True)


@pytest.mark.parametrize('field,value',[('failed_records',1),('rejected_records',1),
    ('persisted_records',19),('unique_source_ids',21),('page_cap',2)])
def test_incomplete_or_invalid_evidence_is_not_a_safe_cap(field,value):
    source=capped_source()
    source['coverage'][field]=value
    assert not source_completed(source)


@pytest.mark.parametrize('kind',['kstartup','bizinfo'])
def test_weekly_api_parameters_and_honest_cap_metadata(kind,monkeypatch):
    a,calls=adapter(kind,[page(kind,[1,2],10)],monkeypatch,max_pages=1,
        weekly_policy=POLICY,scope='OPEN' if kind=='kstartup' else 'API_DEFAULT')
    with pytest.raises(SourceFailure,match='PAGE_LIMIT'):list(a.discover())
    if kind=='kstartup':assert calls[0]['cond[rcrt_prgs_yn::EQ]']=='Y'
    else:assert calls[0]['searchCnt']==2
    report=a.pagination.report()
    assert report['weekly_policy']==POLICY
    assert report['advertised_records']==10 and not report['pagination_complete']


@pytest.mark.parametrize('kind',['kstartup','bizinfo'])
def test_invalid_identity_cannot_be_hidden_by_page_limit(kind,monkeypatch):
    payload=page(kind,[1,2],10)
    rows=payload['data'] if kind=='kstartup' else payload['jsonArray']
    rows.append({})
    a,_=adapter(kind,[payload],monkeypatch,max_pages=1,weekly_policy=POLICY)
    with pytest.raises(SourceFailure,match='API_SCHEMA'):list(a.discover())


@pytest.mark.parametrize('status,exit_code',[('SUCCESS',0),('PARTIAL_SUCCESS',1),('FAILED',1)])
def test_weekly_cli_exit_preserves_real_failures(monkeypatch,status,exit_code):
    from unittest.mock import Mock
    from radar.cli import main
    monkeypatch.setattr('radar.cli.Database',Mock())
    run=Mock(return_value={'status':status})
    monkeypatch.setattr('radar.weekly.run_weekly',run)
    assert main(['weekly','--check-sources'])==exit_code
    assert run.call_args.kwargs['check_sources'] is True
