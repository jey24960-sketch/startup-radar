import json
from types import SimpleNamespace
import pytest
from radar.adapters.official import KStartupApiAdapter,BizInfoApiAdapter
from radar.adapters.base import SourceFailure


def adapter(kind,pages,monkeypatch,**config):
    monkeypatch.setenv('KSTARTUP_API_KEY','FIXTURE_SECRET')
    monkeypatch.setenv('BIZINFO_API_KEY','FIXTURE_SECRET')
    calls=[]
    def get(url,params):
        calls.append(params)
        index=params.get('page',params.get('pageIndex'))
        return json.dumps(pages[index-1]).encode(),'application/json',url
    cls=KStartupApiAdapter if kind=='kstartup' else BizInfoApiAdapter
    return cls({'slug':kind,'config':{'page_size':2,'max_pages':4,**config}},SimpleNamespace(get=get)),calls


def page(kind,ids,total=None):
    if kind=='kstartup':
        return {'data':[{'pbanc_sn':i,'biz_pbanc_nm':str(i),'biz_aply_url':f'https://example.org/{i}'} for i in ids],
                **({'matchCount':total} if total is not None else {})}
    return {'jsonArray':[{'pblancId':str(i),'pblancNm':str(i),'pblancUrl':f'https://example.org/{i}',
                        **({'totCnt':total} if total is not None else {})} for i in ids]}


@pytest.mark.parametrize('kind',['kstartup','bizinfo'])
def test_complete_scope_tracks_unique_ids_duplicates_pages_and_total(kind,monkeypatch):
    a,calls=adapter(kind,[page(kind,[1,2],3),page(kind,[2,3],3)],monkeypatch)
    rows=list(a.discover());report=a.pagination.report()
    assert [r.source_program_id for r in rows]==['1','2','3']
    assert len(calls)==report['pages_requested']==2 and report['records_returned']==4
    assert report['duplicates']==1 and report['unique_source_ids']==report['advertised_records']==3
    assert report['pagination_complete'] and 'FIXTURE_SECRET' not in str(report)


@pytest.mark.parametrize('kind',['kstartup','bizinfo'])
def test_short_page_does_not_hide_advertised_remaining_records(kind,monkeypatch):
    a,calls=adapter(kind,[page(kind,[1],3),page(kind,[2,3],3)],monkeypatch)
    assert len(list(a.discover()))==3 and len(calls)==2
    assert a.pagination.report()['pagination_complete']


@pytest.mark.parametrize('kind',['kstartup','bizinfo'])
def test_cap_is_partial_not_success_and_keeps_measured_denominator(kind,monkeypatch):
    a,_=adapter(kind,[page(kind,[1,2],5)],monkeypatch,max_pages=1)
    rows=[]
    with pytest.raises(SourceFailure,match='PAGE_LIMIT'):
        for row in a.discover():rows.append(row)
    assert len(rows)==2 and not a.pagination.report()['pagination_complete']
    assert a.pagination.report()['advertised_records']==5


@pytest.mark.parametrize('kind',['kstartup','bizinfo'])
def test_empty_before_advertised_end_and_repeated_page_are_failures(kind,monkeypatch):
    a,_=adapter(kind,[page(kind,[1,2],5),page(kind,[],5)],monkeypatch)
    with pytest.raises(SourceFailure,match='PAGINATION_INCOMPLETE'):list(a.discover())
    a,_=adapter(kind,[page(kind,[1,2],5),page(kind,[1,2],5)],monkeypatch)
    with pytest.raises(SourceFailure,match='PAGINATION_STALLED'):list(a.discover())


def test_open_scope_filter_is_applied_to_primary_kstartup_query(monkeypatch):
    a,calls=adapter('kstartup',[page('kstartup',[1],1)],monkeypatch,scope='OPEN')
    list(a.discover())
    assert calls[0]['cond[rcrt_prgs_yn::EQ]']=='Y'
    assert a.pagination.report()['scope']=='OPEN'


@pytest.mark.parametrize('value',[0,-1,True,'2',1001])
def test_invalid_page_configuration_fails_before_network(monkeypatch,value):
    a,calls=adapter('kstartup',[],monkeypatch,max_pages=value)
    with pytest.raises(SourceFailure,match='CONFIGURATION'):list(a.discover())
    assert not calls
