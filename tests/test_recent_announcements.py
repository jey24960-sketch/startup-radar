"""Pre-opening discovery uses the documented unfiltered API, within a clear window."""
import json
from types import SimpleNamespace

import pytest
from radar.adapters.official import KStartupApiAdapter
from radar.adapters.base import AcquiredDetail, SourceFailure


def row(identifier, *, upcoming=False):
    return {'pbanc_sn':identifier,'biz_pbanc_nm':f'예비창업자 모집 {identifier}',
            'biz_aply_url':f'https://example.org/{identifier}',
            'rcrt_prgs_yn':'N' if upcoming else 'Y',
            'pbanc_rcpt_bgng_dt':'20261102' if upcoming else '20261001',
            'pbanc_rcpt_end_dt':'20261120'}


def payload(ids,total,upcoming=()):
    return {'data':[row(identifier,upcoming=identifier in upcoming) for identifier in ids], 'matchCount':total}


def adapter(monkeypatch, responses, **config):
    monkeypatch.setenv('KSTARTUP_API_KEY','FIXTURE_SECRET')
    calls=[]
    def get(url,params):
        calls.append(dict(params))
        scope='featured' if 'cond[biz_pbanc_nm::LIKE]' in params else 'open' if 'cond[rcrt_prgs_yn::EQ]' in params else 'recent'
        return json.dumps(responses[scope][params['page']-1]).encode(),'application/json',url
    source={'slug':'kstartup','name':'K-Startup official API','config':{'scope':'OPEN','page_size':2,'max_pages':3,**config}}
    return KStartupApiAdapter(source,SimpleNamespace(get=get)),calls


def test_unfiltered_window_finds_upcoming_notices_and_deduplicates_all_queries(monkeypatch):
    a,calls=adapter(monkeypatch,{
        'open':[payload([1],1)],'featured':[payload([2],1)],
        'recent':[payload([1,3],1000,upcoming=(3,)),payload([4,5],1000,upcoming=(4,5))],
    },recent_announcement_pages=2,current_title_queries=['Featured'])
    candidates=list(a.discover())
    assert [c.source_program_id for c in candidates]==['1','2','3','4','5']
    assert calls[0]['cond[rcrt_prgs_yn::EQ]']=='Y'
    assert calls[1]['cond[biz_pbanc_nm::LIKE]']=='Featured'
    for call in calls[2:]:
        assert 'cond[rcrt_prgs_yn::EQ]' not in call and 'cond[biz_pbanc_nm::LIKE]' not in call
        assert set(call)=={'serviceKey','page','perPage','returnType'}
    future=candidates[2]
    program=a.normalize(future,AcquiredDetail(future.official_detail_url,'Verified API facts',future.title),[])
    assert program.application_start_at.isoformat()=='2026-11-02T00:00:00+09:00'
    coverage=a.pagination.report()
    assert coverage['scope_completed'] and not coverage['pagination_complete']
    assert coverage['duplicates']==1 and coverage['pages_requested']==4
    window=coverage['queries'][-1]
    assert window['query']=='RECENT_ANNOUNCEMENTS' and window['bounded_window']
    assert window['bounded_window_complete'] and window['window_page_cap']==2
    assert window['advertised_records']==1000 and not window['pagination_complete']
    assert 'FIXTURE_SECRET' not in str(coverage)


@pytest.mark.parametrize('configured',[None,0])
def test_weekly_default_never_adds_the_unfiltered_window(monkeypatch,configured):
    config={} if configured is None else {'recent_announcement_pages':configured}
    a,calls=adapter(monkeypatch,{'open':[payload([1],1)]},**config)
    assert len(list(a.discover()))==1 and len(calls)==1
    assert a.pagination.report()['pagination_complete']
    assert not any(q.get('bounded_window') for q in a.pagination.report()['queries'])


@pytest.mark.parametrize('value',[-1,4,True,'2',None,1.5])
def test_window_configuration_is_bounded_before_any_api_request(monkeypatch,value):
    a,calls=adapter(monkeypatch,{},recent_announcement_pages=value)
    with pytest.raises(SourceFailure,match='CONFIGURATION'):list(a.discover())
    assert calls==[]


def test_window_can_finish_early_only_if_the_api_scope_really_ended(monkeypatch):
    a,calls=adapter(monkeypatch,{'open':[payload([1],1)],'recent':[payload([2],1)]},recent_announcement_pages=3)
    assert [r.source_program_id for r in a.discover()]==['1','2']
    assert len(calls)==2 and a.pagination.report()['pagination_complete']
    assert a.pagination.report()['queries'][-1]['bounded_window_complete']


def test_window_does_not_hide_an_incomplete_primary_scope(monkeypatch):
    a,_=adapter(monkeypatch,{'open':[payload([1,2],4)],'recent':[payload([3],1)]},max_pages=1,recent_announcement_pages=1)
    acquired=[]
    with pytest.raises(SourceFailure,match='PAGE_LIMIT'):
        for candidate in a.discover():acquired.append(candidate)
    assert len(acquired)==3
    assert not a.pagination.report()['scope_completed']
    assert a.pagination.report()['queries'][-1]['bounded_window_complete']


@pytest.mark.parametrize('second,kind',[
    (payload([2,3],1000),'PAGINATION_STALLED'),
    (payload([],1000),'PAGINATION_INCOMPLETE'),
])
def test_repeated_or_missing_recent_pages_are_real_failures(monkeypatch,second,kind):
    a,_=adapter(monkeypatch,{'open':[payload([1],1)],'recent':[payload([2,3],1000),second]},recent_announcement_pages=2)
    with pytest.raises(SourceFailure,match=kind):list(a.discover())
    assert not a.pagination.report()['scope_completed']


def test_bad_identity_cannot_be_hidden_by_the_intentional_window(monkeypatch):
    broken=payload([2],1000);broken['data'].append({})
    a,_=adapter(monkeypatch,{'open':[payload([1],1)],'recent':[broken]},recent_announcement_pages=1)
    with pytest.raises(SourceFailure,match='API_SCHEMA'):list(a.discover())
    assert a.pagination.report()['rejected_records']==1
