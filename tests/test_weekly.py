import os
from datetime import datetime, timedelta
from uuid import uuid4
from unittest.mock import Mock
import pytest
import psycopg
from core.clock import SEOUL
from radar.weekly import build_briefing, snapshot, week_window, announce, run_weekly
from radar.broadcast import SETTING_KEY
from radar.ingestion import ingest
from radar.models import Program
from radar.adapters.base import Candidate, SourceFailure
from radar.adapters.official import KStartupApiAdapter, BizInfoApiAdapter
from test_database import db
from test_weekly_scope import capped_source
from psycopg.types.json import Jsonb

pytestmark=pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Explicit test database required')
AT=datetime(2026,9,14,15,tzinfo=SEOUL)


def configure_official_channel(db,chat_id='-1001234567890',join_url='https://t.me/gfc_startupradar',enabled=True,name='GFC StartupRadar'):
    with db.transaction() as c:
        c.execute("insert into startup_radar.runtime_settings(key,value) values(%s,%s) on conflict(key) do update set value=excluded.value,updated_at=now()",
            (SETTING_KEY,Jsonb({'enabled':enabled,'chat_id':chat_id,'join_url':join_url,'name':name})))


def collection(db, count=3):
    source=db.upsert_source('weekly-k','K-Startup','KSTARTUP',{})
    with db.transaction() as c:
        run=c.execute("insert into startup_radar.ingestion_runs(status,trigger_type,finished_at) values('SUCCESS','weekly-test',now()) returning id").fetchone()['id']
    rows=[]
    for i in range(count):
        # Broadly applicable early-founder programs: actionable and GFC_RELEVANT,
        # so these fixtures exercise publication rather than the relevance gate.
        p=Program(title=f'예비창업자 액셀러레이팅 프로그램 {i}',organization='Agency',official_url=f'https://example.org/{i}',
            support_summary='Official support',application_end_at=datetime(2027,1,1,tzinfo=SEOUL),application_end_precision='DATE',deadline_type='FIXED_DATE')
        saved=db.save_program(p,source['id'],str(i),p.official_url,{},'Official structured fields')
        rows.append({**saved,'snapshot':snapshot(p,{}),'status':'OPEN'})
    return {'id':str(run),'status':'SUCCESS','sources':[{'status':'SUCCESS','parsed':count,'coverage':{'pagination_complete':True}} for _ in range(2)],'weekly_programs':rows}


def test_week_is_seoul_monday_through_sunday():
    assert tuple(map(str,week_window(AT)))==('2026-09-14','2026-09-20')
    assert week_window(AT+timedelta(days=6,hours=8))[0]==AT.date()
    with pytest.raises(ValueError):week_window(AT.replace(tzinfo=None))


def test_many_programs_one_post_dedup_and_same_week_stable(db):
    acquired=collection(db)
    acquired['weekly_programs'].append(acquired['weekly_programs'][0])
    first=build_briefing(db,acquired,AT)
    assert first['published'] and first['item_count']==3 and first['new_count']==3
    acquired['weekly_programs'][0]['snapshot']['title']='Do not overwrite published content'
    second=build_briefing(db,acquired,AT)
    assert second['unchanged'] and second['briefing_id']==first['briefing_id']
    with db.transaction() as c:
        assert c.execute('select count(*) n from startup_radar.weekly_briefings').fetchone()['n']==1
        assert c.execute('select count(*) n from startup_radar.weekly_briefing_items').fetchone()['n']==3
        assert c.execute("select count(*) n from startup_radar.weekly_briefing_items where snapshot->>'title' like 'Do not%'").fetchone()['n']==0


def test_unchanged_not_repeated_material_update_and_archive(db):
    acquired=collection(db)
    first=build_briefing(db,acquired,AT)
    acquired['weekly_programs'][0]['snapshot']['application_end_at']='2027-01-10T00:00:00+09:00'
    # Actionability now reads the official end date against the publication
    # reference, so a closed notice is expressed as a past deadline.
    acquired['weekly_programs'][1]['snapshot']['application_end_at']='2026-09-01T23:59:59+09:00'
    second=build_briefing(db,acquired,AT+timedelta(days=7))
    assert (second['item_count'],second['new_count'],second['updated_count'])==(1,0,1)
    third=build_briefing(db,acquired,AT+timedelta(days=14))
    assert third['published'] and third['item_count']==0
    with db.transaction() as c:
        assert c.execute('select count(*) n from startup_radar.weekly_briefings').fetchone()['n']==3
        assert c.execute('select item_count from startup_radar.weekly_briefings where id=%s',(first['briefing_id'],)).fetchone()['item_count']==3


@pytest.mark.parametrize('case,expected', [('failed',False),('partial-empty',False),('partial-useful',True),('complete-empty',True)])
def test_failed_collection_never_becomes_empty_week(db,case,expected):
    acquired=collection(db,1 if case=='partial-useful' else 0)
    if case!='complete-empty':acquired['sources'][1]={'status':'FAILED','parsed':0,'coverage':{'pagination_complete':False}}
    if case=='failed':acquired['sources'][0]=acquired['sources'][1]
    result=build_briefing(db,acquired,AT)
    assert result['published'] is expected
    if case=='partial-useful':assert result['status']=='PARTIAL_SUCCESS'
    with db.transaction() as c:
        assert c.execute('select count(*) n from startup_radar.weekly_briefings').fetchone()['n']==int(expected)


def test_draft_regenerate_and_publish_same_id(db):
    acquired=collection(db,1)
    draft=build_briefing(db,acquired,AT,publish=False)
    assert not draft['published']
    acquired['weekly_programs'][0]['snapshot']['support_summary']='Updated official benefit'
    published=build_briefing(db,acquired,AT)
    assert published['briefing_id']==draft['briefing_id'] and published['published']
    with db.transaction() as c:assert c.execute('select revision from startup_radar.weekly_briefings').fetchone()['revision']==2


def test_explicit_published_revision_retains_prior_items_and_publication_identity(db):
    acquired=collection(db,1)
    first=build_briefing(db,acquired,AT)
    acquired['weekly_programs'][0]['snapshot']['application_end_at']='2027-01-10T23:59:59+09:00'
    revised=build_briefing(db,acquired,AT,revision_note='Correct verified official API calendar format')
    assert revised['briefing_id']==first['briefing_id']
    with db.transaction() as c:
        assert c.execute('select count(*) n from startup_radar.weekly_briefings').fetchone()['n']==1
        assert c.execute('select revision from startup_radar.weekly_briefings').fetchone()['revision']==2
        audit=c.execute("select detail from startup_radar.admin_audit where action='WEEKLY_BRIEFING_REVISION'").fetchone()['detail']
        assert audit['items'][0]['snapshot']['application_end_at'].startswith('2027-01-01')
        assert audit['previous_revision']==1
    with pytest.raises(ValueError):build_briefing(db,acquired,AT,revision_note='')


def test_member_rpc_requires_verified_gfc_membership_without_team(db):
    result=build_briefing(db,collection(db),AT)
    member,external=uuid4(),uuid4()
    with db.transaction() as c:
        c.execute('insert into auth.users(id) values(%s),(%s)',(member,external))
        c.execute("insert into public.test_gfc_roles values(%s,'member'),(%s,'external')",(member,external))
    with db.transaction(member) as c:
        assert c.execute('select public.gfc_radar_weekly_briefings() data').fetchone()['data']['total']==1
        article=c.execute('select public.gfc_radar_weekly_briefing(%s) data',(result['briefing_id'],)).fetchone()['data']
        assert len(article['items'])==3
        assert all(set(item)=={'program_id','display_order','change_type','facts',
            'relevance_status','restriction_summary','stage_fit'} for item in article['items'])
    with db.transaction() as c:
        stored=c.execute('select program_id,display_order from startup_radar.weekly_briefing_items where briefing_id=%s order by display_order,program_id',
            (result['briefing_id'],)).fetchall()
        assert [(item['program_id'],item['display_order']) for item in article['items']]==[
            (str(row['program_id']),row['display_order']) for row in stored]
    with db.transaction(external) as c:assert c.execute('select count(*) n from startup_radar.weekly_briefings').fetchone()['n']==0
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with db.transaction(external) as c:c.execute('select public.gfc_radar_weekly_briefings()')
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with db.transaction() as c:
            c.execute('set local role anon');c.execute('select public.gfc_radar_weekly_briefing(%s)',(result['briefing_id'],))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with db.transaction(member) as c:c.execute("update startup_radar.weekly_briefings set title='unauthorized'")


@pytest.mark.parametrize('state',['DELIVERED','UNCERTAIN','FAILED'])
def test_one_weekly_announcement_and_no_duplicate_or_uncertain_resend(db,state):
    # The normal weekly briefing goes to ONE official channel. Team subscriptions
    # are not consulted, so an enabled team subscription alone changes nothing.
    result=build_briefing(db,collection(db),AT)
    transport=Mock();transport.send.return_value={'state':state,'receipt':{'message_id':17} if state=='DELIVERED' else None}
    assert announce(db,result['briefing_id'],transport)['state']=='NO_BROADCAST_CHANNEL'
    user=uuid4()
    with db.transaction() as c:c.execute('insert into auth.users(id) values(%s)',(user,))
    team=db.create_team('Weekly fixture',user)
    with db.transaction() as c:
        c.execute("insert into startup_radar.telegram_subscriptions(team_id,chat_id,enabled,digest_enabled,channel_health) values(%s,'fixture-weekly',true,true,'HEALTHY')",(team['id'],))
    assert announce(db,result['briefing_id'],transport)['state']=='NO_BROADCAST_CHANNEL'
    configure_official_channel(db,chat_id='-1001234567890',join_url='https://t.me/gfc_startupradar')
    assert announce(db,result['briefing_id'])['state']=='DELIVERY_DISABLED'
    first=announce(db,result['briefing_id'],transport)
    announce(db,result['briefing_id'],transport)
    assert transport.send.call_count==1
    assert transport.send.call_args.args[0]=='-1001234567890'
    assert '/notice/weekly/'+result['briefing_id'] in transport.send.call_args.args[1]
    assert first['states'][state]==1
    with db.transaction() as c:
        assert c.execute('select count(*) n from startup_radar.notification_batches').fetchone()['n']==0
        row=c.execute("select target_kind,subscription_id,chat_id from startup_radar.weekly_announcements").fetchone()
        assert (row['target_kind'],row['subscription_id'],row['chat_id'])==('OFFICIAL_CHANNEL',None,'-1001234567890')


def test_weekly_official_ingestion_never_calls_ai_documents_or_team_calculation(db,monkeypatch):
    sources=[db.upsert_source('weekly-k','K','KSTARTUP',{}),db.upsert_source('weekly-b','B','BIZINFO',{})]
    monkeypatch.setattr('radar.ingestion.RequirementExtractor',Mock(side_effect=AssertionError('AI must not be instantiated')))
    adapters=[]
    def factory(s):
        klass=KStartupApiAdapter if s['adapter']=='KSTARTUP' else BizInfoApiAdapter
        adapter=klass(s,Mock())
        raw={'pbanc_sn':1,'biz_pbanc_nm':'Official fixture','pbanc_ctnt':'Official support','pbanc_rcpt_end_dt':'20271231'} if s['adapter']=='KSTARTUP' else {'bsnsSumryCn':'Official support','reqstBeginEndDe':'20260901 ~ 20271231'}
        candidate=Candidate(s['slug'],'1',f"https://example.org/{s['slug']}",f"https://example.org/{s['slug']}",'Official fixture',raw)
        adapter.discover=lambda:iter([candidate]);adapter.fetch_detail=Mock(side_effect=AssertionError('No portal dependency'))
        adapter.fetch_documents=Mock(side_effect=AssertionError('No OCR dependency'))
        adapters.append(adapter);return adapter
    result=ingest(db,sources,adapter_factory=factory,structured_only=True)
    assert result['status']=='SUCCESS' and len(result['weekly_programs'])==2
    assert all(not a.fetch_detail.called and not a.fetch_documents.called for a in adapters)
    assert all(row['snapshot']['applicant_summary']=='공식 공고 확인 필요' for row in result['weekly_programs'])


def test_weekly_rerun_does_not_recollect_published_week(db):
    first=build_briefing(db,collection(db),AT)
    collector=Mock(side_effect=AssertionError('Published week must stay stable'))
    second=run_weekly(db,at=AT,collector=collector)
    assert second['status']=='SUCCESS' and second['briefing_id']==first['briefing_id']
    assert second['announcement']['state']=='NO_BROADCAST_CHANNEL'
    assert not collector.called


def test_bounded_publication_is_healthy_but_keeps_partial_coverage_and_stable_rerun(db):
    acquired=collection(db)
    acquired['status']='PARTIAL_SUCCESS'
    acquired['sources']=[capped_source(),capped_source()]
    with db.transaction() as c:
        c.execute('update startup_radar.ingestion_runs set status=%s,summary=%s where id=%s',
            (acquired['status'],Jsonb({'sources':acquired['sources']}),acquired['id']))
    first=build_briefing(db,acquired,AT)
    assert first['status']=='SUCCESS' and first['collection_status']=='PARTIAL_SUCCESS'
    second=run_weekly(db,at=AT,collector=Mock(side_effect=AssertionError('No recollection')))
    assert second['status']=='SUCCESS' and second['briefing_id']==first['briefing_id']
    assert second['collection_status']=='PARTIAL_SUCCESS' and second['unchanged']
    with db.transaction() as c:
        row=c.execute('select * from startup_radar.weekly_briefings').fetchone()
        assert row['revision']==1 and row['collection_status']=='PARTIAL_SUCCESS'


@pytest.mark.parametrize('failed_sources',[0,1,2])
def test_explicit_source_check_keeps_article_and_real_failures_visible(db,failed_sources):
    acquired=collection(db)
    first=build_briefing(db,acquired,AT)
    db.upsert_source('weekly-b','BizInfo','BIZINFO',{})
    with db.transaction() as c:
        before=c.execute('select to_jsonb(b) data from startup_radar.weekly_briefings b').fetchone()['data']
    acquired['sources']=[capped_source(),capped_source()]
    for i in range(failed_sources):
        acquired['sources'][i]={'status':'FAILED','parsed':0,'failures':[{'kind':'HTTP_401'}]}
    acquired['status']='FAILED' if failed_sources==2 else 'PARTIAL_SUCCESS'
    acquired['weekly_programs'][0]['snapshot']['title']='Must not rewrite current issue'
    collector=Mock(return_value=acquired);transport=Mock()
    result=run_weekly(db,transport,at=AT,collector=collector,check_sources=True)
    assert result['status']==['SUCCESS','PARTIAL_SUCCESS','FAILED'][failed_sources]
    assert result['briefing_id']==first['briefing_id'] and result['unchanged']
    assert collector.call_count==1 and not transport.send.called
    if failed_sources==2:assert 'announcement' not in result
    assert all(s['config']['max_pages']==1 for s in collector.call_args.args[1])
    with db.transaction() as c:
        assert c.execute('select to_jsonb(b) data from startup_radar.weekly_briefings b').fetchone()['data']==before
        assert c.execute('select count(*) n from startup_radar.admin_audit').fetchone()['n']==0


def test_published_real_source_failure_does_not_turn_green_on_rerun(db):
    acquired=collection(db)
    acquired['sources'][1]={'status':'FAILED','parsed':0,'failures':[{'kind':'NETWORK'}]}
    with db.transaction() as c:
        c.execute('update startup_radar.ingestion_runs set summary=%s where id=%s',
            (Jsonb({'sources':acquired['sources']}),acquired['id']))
    build_briefing(db,acquired,AT)
    result=run_weekly(db,at=AT)
    assert result['status']=='PARTIAL_SUCCESS'


def test_real_adapter_contract_through_ingestion_and_weekly_publication(db,monkeypatch):
    from test_official_pagination import adapter,page
    from radar.weekly_scope import weekly_sources
    sources=weekly_sources([db.upsert_source(kind,kind,kind.upper(),{})
        for kind in ('kstartup','bizinfo')])
    def factory(source):
        kind=source['slug']
        a,_=adapter(kind,[page(kind,[1,2],10)],monkeypatch,**source['config'])
        a.source=source
        return a
    acquired=ingest(db,sources,adapter_factory=factory,structured_only=True)
    assert acquired['status']=='PARTIAL_SUCCESS'
    assert all(s['parsed']==2 and s['failures'][0]['kind']=='PAGE_LIMIT' for s in acquired['sources'])
    result=build_briefing(db,acquired,AT)
    assert result['status']=='SUCCESS' and result['published']
    assert result['collection_status']=='PARTIAL_SUCCESS'
    with db.transaction() as c:
        assert c.execute('select count(*) n from startup_radar.sources where last_successful_full_scan_at is not null').fetchone()['n']==0
