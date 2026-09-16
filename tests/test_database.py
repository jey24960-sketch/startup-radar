import os
from uuid import uuid4
from datetime import timedelta
import pytest
from radar.database import Database
from radar.models import Program,TeamProfile,update_profile
from radar.dates import korean_date
from radar.identity import normalize_text,normalize_url

pytestmark=pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Explicit local PostgreSQL test database required')


@pytest.fixture
def db():
    database=Database(os.environ['TEST_DATABASE_URL'])
    with database.transaction() as c:
        marker=c.execute('select value from public.radar_test_marker').fetchone()
        assert marker and marker['value']=='ephemeral-test-only', 'Refusing to reset a non-test database'
        c.execute('truncate auth.users,startup_radar.teams,startup_radar.sources,startup_radar.programs,startup_radar.ingestion_runs,startup_radar.notification_runs cascade')
        c.execute('truncate startup_radar.telegram_updates,startup_radar.schedule_claims cascade')
        c.execute('truncate startup_radar.worker_executions cascade')
        c.execute("update startup_radar.runtime_settings set value=value || '{\"enabled\":true,\"ingestion_enabled\":true}'::jsonb where key='scheduling'")
        # The official weekly channel is operator state, not per-test data: start every test unconfigured.
        c.execute("update startup_radar.runtime_settings set value='{\"enabled\":false,\"chat_id\":null,\"name\":\"GFC StartupRadar\",\"join_url\":null}'::jsonb where key='weekly_telegram_channel'")
    return database


def source(db):
    return db.upsert_source(str(uuid4()),'Fixture source','HTML',{})['id']


def program():
    return Program(title='2026 GFC 창업 지원',organization='Test institute',official_url='https://example.org/notice/'+str(uuid4()),
        application_end_at=korean_date('20261231',True),deadline_type='FIXED_DATE')


def test_profile_history_and_team_isolation(db):
    a,b=uuid4(),uuid4()
    with db.transaction() as c:
        c.execute('insert into auth.users(id) values(%s),(%s)',(a,b))
    ta=db.create_team('A',a);tb=db.create_team('B',b)
    p=update_profile(TeamProfile(),{'region':'Seoul'})
    db.save_profile(ta['id'],p,a,1)
    with db.transaction(a) as c:
        versions=c.execute('select * from startup_radar.team_profile_versions where team_id=%s order by version',(ta['id'],)).fetchall()
        assert [v['version'] for v in versions]==[1,2]
        assert versions[0]['profile']['region'] is None and versions[1]['profile']['region']=='Seoul'
        assert c.execute('select * from startup_radar.team_profiles where team_id=%s',(tb['id'],)).fetchone() is None
    with pytest.raises(PermissionError): db.save_profile(tb['id'],p,a,1)
    with pytest.raises(ValueError): db.save_profile(ta['id'],p,a,1)


def test_cross_source_provenance_and_identical_version(db):
    p=program();a,b=source(db),source(db)
    x=db.save_program(p,a,'a1',p.official_url,{},'raw')
    y=db.save_program(p,b,'b1',p.official_url+'?utm_source=b',{},'raw')
    assert x['program_id']==y['program_id'] and x['version_id']==y['version_id']
    with db.transaction() as c:
        assert c.execute('select count(*) n from startup_radar.program_sources where program_id=%s',(x['program_id'],)).fetchone()['n']==2


def test_changed_url_and_deadline_extension_create_versions(db):
    p=program();s=source(db)
    x=db.save_program(p,s,'stable-id',p.official_url,{},'raw')
    p.application_end_at+=timedelta(days=10)
    p.official_url+='/updated';p.application_url=p.official_url+'/apply'
    y=db.save_program(p,s,'stable-id',p.official_url,{},'updated')
    assert x['program_id']==y['program_id'] and x['version_id']!=y['version_id'] and y['event']=='UPDATE'
    with db.transaction() as c:
        events=c.execute('select * from startup_radar.program_change_events where version_id=%s',(y['version_id'],)).fetchall()
        assert 'application_end_at' in events[0]['changed_fields']


def test_fuzzy_duplicates_are_not_merged(db):
    p=program();s=source(db)
    x=db.save_program(p,s,'one',p.official_url,{},'one')
    p.official_url+='/another'
    y=db.save_program(p,s,'two',p.official_url,{},'two')
    assert x['program_id']!=y['program_id']
    with db.transaction() as c:
        assert c.execute('select * from startup_radar.possible_duplicates where program_id=%s and candidate_program_id=%s',(y['program_id'],x['program_id'])).fetchone()


def test_distinct_publisher_ids_on_same_url_remain_distinct(db):
    p=program();s=source(db)
    first=db.save_program(p,s,'round-one',p.official_url,{'round':1},'first')
    second=db.save_program(p,s,'round-two',p.official_url,{'round':2},'second')
    assert first['program_id']!=second['program_id']
    again=db.save_program(p,s,'round-two',p.official_url,{'round':2},'second')
    assert again['version_id']==second['version_id']
    with db.transaction() as c:
        assert c.execute('select count(*) n from startup_radar.program_sources').fetchone()['n']==2
        assert c.execute('select count(*) n from startup_radar.possible_duplicates').fetchone()['n']==1


def test_authoritative_id_wins_when_url_now_matches_another_notice(db):
    p=program();s=source(db);other=p.model_copy(deep=True);other.official_url+='/other'
    first=db.save_program(p,s,'stable-id',p.official_url,{},'one')
    second=db.save_program(other,s,'other-id',other.official_url,{},'two')
    p.official_url=other.official_url
    updated=db.save_program(p,s,'stable-id',p.official_url,{},'changed URL')
    assert updated['program_id']==first['program_id'] and updated['program_id']!=second['program_id']


def test_shared_url_from_other_source_with_different_title_is_review_only(db):
    p=program();a,b=source(db),source(db)
    first=db.save_program(p,a,'a',p.official_url,{},'one')
    p.title='Completely separate 2027 program'
    second=db.save_program(p,b,'b',p.official_url,{},'two')
    assert first['program_id']!=second['program_id']


def test_ambiguous_cross_source_url_does_not_choose_first_record(db):
    p=program();a,b=source(db),source(db)
    first=db.save_program(p,a,'a1',p.official_url,{},'one')
    second=db.save_program(p,a,'a2',p.official_url,{},'two')
    third=db.save_program(p,b,'b',p.official_url,{},'three')
    assert len({first['program_id'],second['program_id'],third['program_id']})==3


def test_unidentified_source_url_keeps_versions_and_can_gain_an_id(db):
    p=program();s=source(db)
    first=db.save_program(p,s,None,p.official_url,{},'one')
    p.title+=' revised'
    second=db.save_program(p,s,None,p.official_url,{},'two')
    identified=db.save_program(p,s,'now-known',p.official_url,{},'two')
    assert first['program_id']==second['program_id']==identified['program_id']
    assert first['version_id']!=second['version_id']==identified['version_id']


def test_normalization():
    assert normalize_text('ＧＦＣ 창업 - 지원')==normalize_text('GFC창업지원')
    assert normalize_url('https://example.org/p?utm_source=x&id=2#top')=='https://example.org/p?id=2'
from radar.adapters.base import SourceAdapter,Candidate,AcquiredDetail,SourceFailure
from radar.models import Program
from radar.ingestion import ingest


def test_source_failure_does_not_erase_success(db):
    ok=db.upsert_source('integration-good','Good','RSS',{})
    bad=db.upsert_source('integration-failed','Failed','HTML',{})
    class Adapter(SourceAdapter):
        def discover(self):yield Candidate('integration-good','notice-id','https://example.org/integration','https://example.org/integration','Opportunity',{})
        def fetch_detail(self,c):return AcquiredDetail(c.official_detail_url,'Eligibility text','Opportunity')
        def fetch_documents(self,d):return []
        def normalize(self,c,d,docs):return Program(title=c.title,organization='Agency',official_url=d.url)
    class Extractor:
        def extract(self,p,*args):return p
    def factory(s):
        if s['id']==bad['id']:raise SourceFailure('BLOCKED','Source denied access')
        return Adapter()
    run=ingest(db,[ok,bad],adapter_factory=factory,extractor=Extractor())
    assert run['status']=='PARTIAL_SUCCESS'
    assert run['sources'][0]['parsed']==1 and run['sources'][1]['status']=='FAILED'
    with db.transaction() as c:
        assert c.execute('select count(*) n from startup_radar.source_run_results where run_id=%s',(run['id'],)).fetchone()['n']==2
        assert c.execute('select * from startup_radar.program_sources where source_id=%s',(ok['id'],)).fetchone()


def test_api_only_detail_is_persisted_without_ai_or_confident_eligibility(db):
    s=db.upsert_source('api-only-check','Official API','KSTARTUP',{})
    class Adapter(SourceAdapter):
        def discover(self):yield Candidate('api-only-check','retained-id','https://example.org/retained','https://example.org/retained','Retained official notice',{'official':True})
        def fetch_detail(self,c):return AcquiredDetail(c.official_detail_url,'API summary',c.title,evidence_warning='DETAIL_UNAVAILABLE')
        def fetch_documents(self,d):return []
        def normalize(self,c,d,docs):return Program(title=c.title,organization='Agency',official_url=d.url,evidence_complete=True)
    class Extractor:
        def extract(self,*args):raise AssertionError('Missing body must not trigger an AI guess')
    result=ingest(db,[s],adapter_factory=lambda source:Adapter(),extractor=Extractor())
    assert result['sources'][0]['parsed']==1
    assert result['sources'][0]['failures'][0]['kind']=='DETAIL_UNAVAILABLE'
    with db.transaction() as c:
        row=c.execute('select v.normalized from startup_radar.program_sources ps join startup_radar.programs p on p.id=ps.program_id join startup_radar.program_versions v on v.id=p.current_version_id where ps.source_id=%s',(s['id'],)).fetchone()
    assert row['normalized']['evidence_complete'] is False
from radar.models import Evidence,Requirement
from radar.recommendations import refresh_recommendations
from radar.notifications import plan_notifications,deliver_pending
from core.clock import now


def test_notification_idempotency_and_partial_delivery(db):
    owner=uuid4()
    with db.transaction() as c:c.execute('insert into auth.users values(%s)',(owner,))
    team=db.create_team('Notification team',owner,TeamProfile(business_status='PRE_BUSINESS'))
    s=source(db)
    for i in range(2):
        p=program();p.title+=str(i);p.program_types=['GRANT'];p.evidence_complete=True
        p.application_end_at=now()+timedelta(days=7)
        p.requirements=[Requirement(key='business_status',operator='EQ',value='PRE_BUSINESS',certain=True,
            evidence=[Evidence(source_id=str(s),text='예비창업자만 신청 가능',method='MANUAL',verified=True,confidence=1)])]
        db.save_program(p,s,str(uuid4()),p.official_url,{},'source')
    with db.transaction() as c:c.execute('insert into startup_radar.telegram_subscriptions(team_id,chat_id,channel_health) values(%s,%s,$health$HEALTHY$health$)',(team['id'],'fixture-chat'))
    refresh_recommendations(db,team['id'])
    first=plan_notifications(db,'REMINDER');second=plan_notifications(db,'REMINDER')
    assert first==2 and second==0
    class Transport:
        count=0
        def send(self,chat,text):
            self.count+=1
            assert '지원 가능 여부: 지원 가능' in text
            return {'state':'DELIVERED','receipt':{'message_id':123}} if self.count==1 else {'state':'FAILED','error':'fixture rejection'}
    result=deliver_pending(db,Transport(),'REMINDER')
    assert result['delivered']==1 and result['failed']==1
    with db.transaction() as c:
        items=c.execute('select state,delivered_at from startup_radar.notification_items where team_id=%s',(team['id'],)).fetchall()
        assert sum(item['delivered_at'] is not None for item in items)==1
    assert deliver_pending(db,Transport(),'REMINDER')['delivered']==0


def test_scoped_notification_never_plans_or_claims_other_subscriptions(db):
    owner=uuid4()
    with db.transaction() as c:c.execute('insert into auth.users values(%s)',(owner,))
    team=db.create_team('Scoped notification fixture',owner,TeamProfile())
    p=program();p.program_types=['EDUCATION'];p.evidence_complete=True;p.application_end_at=now()+timedelta(days=14)
    db.save_program(p,source(db),'scope',p.official_url,{},'fixture')
    with db.transaction() as c:
        ids=[c.execute('insert into startup_radar.telegram_subscriptions(team_id,chat_id,channel_health) values(%s,%s,$health$HEALTHY$health$) returning id',
                       (team['id'],chat)).fetchone()['id'] for chat in ('approved-fixture','other-fixture')]
    refresh_recommendations(db)
    assert plan_notifications(db,'DIGEST',subscription_id=ids[0])==1
    with db.transaction() as c:
        assert c.execute('select distinct subscription_id from startup_radar.notification_items').fetchall()==[{'subscription_id':ids[0]}]
    assert plan_notifications(db,'DIGEST',subscription_id=ids[1])==1
    class Transport:
        calls=0
        def send(self,chat,text):
            assert chat=='approved-fixture';self.calls+=1
            return {'state':'DELIVERED','receipt':{'message_id':17}}
    transport=Transport()
    assert deliver_pending(db,transport,'DIGEST',subscription_id=ids[0])['delivered']==1
    assert plan_notifications(db,'DIGEST',subscription_id=ids[0])==0
    assert deliver_pending(db,transport,'DIGEST',subscription_id=ids[0])['delivered']==0
    assert transport.calls==1
    with db.transaction() as c:
        assert c.execute('select state from startup_radar.notification_batches where subscription_id=%s',(ids[1],)).fetchone()['state']=='PENDING'


def test_document_evidence_links_to_same_program_version(db):
    p=program();s=source(db)
    p.requirements=[Requirement(key='founder_age',operator='LTE',value=39,certain=True,
        evidence=[Evidence(document_id='fixture-document-hash',text='Age <=39',method='MANUAL',verified=True,confidence=1)])]
    saved=db.save_program(p,s,'document-evidence',p.official_url,{},'Fixture',documents=[{
        'original_url':'https://example.org/evidence.pdf','filename':'evidence.pdf','content_hash':'fixture-document-hash',
        'fetch_status':'SUCCESS','extraction_status':'SUCCESS','extracted_text':'Age <=39'}])
    with db.transaction() as c:
        row=c.execute('select r.document_id,d.program_version_id from startup_radar.program_requirements r join startup_radar.documents d on d.id=r.document_id where r.program_version_id=%s',(saved['version_id'],)).fetchone()
        assert row and row['program_version_id']==saved['version_id']


def test_original_source_observation_survives_updates(db):
    p=program();s=source(db)
    first=db.save_program(p,s,'stable-source',p.official_url,{'deadline':'original'},'source v1',extraction_metadata={'model':'fixture-v1'})
    p.application_end_at+=timedelta(days=7)
    second=db.save_program(p,s,'stable-source',p.official_url,{'deadline':'extended'},'source v2',extraction_metadata={'model':'fixture-v2'})
    db.save_program(p,s,'stable-source',p.official_url,{'deadline':'extended'},'source v2',extraction_metadata={'model':'fixture-v2'})
    with db.transaction() as c:
        snapshots=c.execute('select * from startup_radar.program_source_snapshots order by observed_at').fetchall()
        assert len(snapshots)==2
        assert snapshots[0]['program_version_id']==first['version_id'] and snapshots[0]['raw_metadata']=={'deadline':'original'}
        assert snapshots[0]['extraction_metadata']['model']=='fixture-v1'
        assert snapshots[1]['program_version_id']==second['version_id']


def test_ocr_draft_survives_unchanged_version_without_rewriting_trusted_documents(db):
    p=program();s=source(db)
    doc={'original_url':'https://example.org/poster.png','filename':'poster.png','content_hash':'fixture-image',
         'fetch_status':'SUCCESS','extraction_status':'FAILED','error_kind':'DOCUMENT_OCR_REQUIRED'}
    first=db.save_program(p,s,'ocr-source',p.official_url,{},'same source',documents=[doc])
    doc.update(error_kind='DOCUMENT_OCR_REVIEW',ocr_review={'review_required':True,'pages':[{'page':1,'text':'attendance required'}]})
    metadata={'review_flags':[]}
    second=db.save_program(p,s,'ocr-source',p.official_url,{},'same source',documents=[doc],extraction_metadata=metadata)
    db.save_program(p,s,'ocr-source',p.official_url,{},'same source',documents=[doc],extraction_metadata=metadata)
    assert first['version_id']==second['version_id'] and second['event'] is None and metadata=={'review_flags':[]}
    with db.transaction() as c:
        rows=c.execute('select extraction_metadata from startup_radar.program_source_snapshots order by observed_at').fetchall()
        assert len(rows)==2
        review=rows[-1]['extraction_metadata']['document_ocr_reviews'][0]
        assert review['content_hash']=='fixture-image' and review['draft']['review_required']
        original=c.execute('select extraction_status,extracted_text from startup_radar.documents').fetchone()
        assert original['extraction_status']=='FAILED' and original['extracted_text'] is None


def test_adding_untrusted_ocr_draft_does_not_repeat_ai_analysis(db):
    from radar.analysis_cache import extract_cached
    from radar.adapters.base import AcquiredDetail
    p=program();s=source(db);detail=AcquiredDetail(p.official_url,'same source',p.title)
    doc={'original_url':'https://example.org/poster','content_hash':'fixture',
         'fetch_status':'SUCCESS','extraction_status':'FAILED','error_kind':'DOCUMENT_OCR_REQUIRED'}
    class Extractor:
        calls=0
        def extract(self,program,*args):
            self.calls+=1
            return program
    extractor=Extractor()
    extract_cached(db,extractor,p,detail,[doc],s,{})
    doc.update(error_kind='DOCUMENT_OCR_REVIEW',ocr_review={'review_required':True,'pages':[{'text':'draft'}]})
    metadata={}
    extract_cached(db,extractor,p,detail,[doc],s,metadata)
    assert extractor.calls==1 and metadata['cache_hit']


def test_parallel_snapshot_is_read_only_and_does_not_invent_collection_time(db):
    from radar.parallel import v2_snapshot,compare
    owner=uuid4()
    with db.transaction() as c:c.execute('insert into auth.users values(%s)',(owner,))
    team=db.create_team('Comparison fixture',owner,TeamProfile(business_status='PRE_BUSINESS'))
    p=program();p.program_types=['GRANT'];p.evidence_complete=True;s=source(db)
    saved=db.save_program(p,s,'comparison',p.official_url,{'fixture':True},'source')
    snapshot=v2_snapshot(db,team['id'])
    assert snapshot['observed_at'] is None and snapshot['profile_version_id']
    assert snapshot['programs'][0]['id']==str(saved['program_id'])
    assert snapshot['scope']=='STORED_CATALOG'
    assert snapshot['programs'][0]['source_observations'][0]['last_seen_at']
    assert snapshot['programs'][0]['application_end_precision']==p.application_end_precision
    assert snapshot['source_results'][0]['run_id'] is None
    report=compare({'status':'SUCCESS','observed_at':now().isoformat(),'all_programs':[{'title':p.title,'organization':p.organization,'apply_url':p.official_url}]},snapshot)
    assert report['counts']['matched']==1 and report['cutover_approved'] is False
    with db.transaction() as c:
        assert c.execute('select count(*) n from startup_radar.recommendations').fetchone()['n']==0
        assert c.execute('select count(*) n from startup_radar.notification_items').fetchone()['n']==0
    with db.transaction(owner) as c:
        assert c.execute('select count(*) n from startup_radar.program_source_snapshots').fetchone()['n']==0
