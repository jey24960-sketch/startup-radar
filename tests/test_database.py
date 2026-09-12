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
    return Database(os.environ['TEST_DATABASE_URL'])


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
        versions=c.execute('select * from radar.team_profile_versions where team_id=%s order by version',(ta['id'],)).fetchall()
        assert [v['version'] for v in versions]==[1,2]
        assert versions[0]['profile']['region'] is None and versions[1]['profile']['region']=='Seoul'
        assert c.execute('select * from radar.team_profiles where team_id=%s',(tb['id'],)).fetchone() is None
    with pytest.raises(PermissionError): db.save_profile(tb['id'],p,a,1)
    with pytest.raises(ValueError): db.save_profile(ta['id'],p,a,1)


def test_cross_source_provenance_and_identical_version(db):
    p=program();a,b=source(db),source(db)
    x=db.save_program(p,a,'a1',p.official_url,{},'raw')
    y=db.save_program(p,b,'b1',p.official_url+'?utm_source=b',{},'raw')
    assert x['program_id']==y['program_id'] and x['version_id']==y['version_id']
    with db.transaction() as c:
        assert c.execute('select count(*) n from radar.program_sources where program_id=%s',(x['program_id'],)).fetchone()['n']==2


def test_changed_url_and_deadline_extension_create_versions(db):
    p=program();s=source(db)
    x=db.save_program(p,s,'stable-id',p.official_url,{},'raw')
    p.application_end_at+=timedelta(days=10)
    p.official_url+='/updated';p.application_url=p.official_url+'/apply'
    y=db.save_program(p,s,'stable-id',p.official_url,{},'updated')
    assert x['program_id']==y['program_id'] and x['version_id']!=y['version_id'] and y['event']=='UPDATE'
    with db.transaction() as c:
        events=c.execute('select * from radar.program_change_events where version_id=%s',(y['version_id'],)).fetchall()
        assert 'application_end_at' in events[0]['changed_fields']


def test_fuzzy_duplicates_are_not_merged(db):
    p=program();s=source(db)
    x=db.save_program(p,s,'one',p.official_url,{},'one')
    p.official_url+='/another'
    y=db.save_program(p,s,'two',p.official_url,{},'two')
    assert x['program_id']!=y['program_id']
    with db.transaction() as c:
        assert c.execute('select * from radar.possible_duplicates where program_id=%s and candidate_program_id=%s',(y['program_id'],x['program_id'])).fetchone()


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
        assert c.execute('select count(*) n from radar.source_run_results where run_id=%s',(run['id'],)).fetchone()['n']==2
        assert c.execute('select * from radar.program_sources where source_id=%s',(ok['id'],)).fetchone()
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
    with db.transaction() as c:c.execute('insert into radar.telegram_subscriptions(team_id,chat_id) values(%s,%s)',(team['id'],'fixture-chat'))
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
        items=c.execute('select state,delivered_at from radar.notification_items where team_id=%s',(team['id'],)).fetchall()
        assert sum(item['delivered_at'] is not None for item in items)==1
    assert deliver_pending(db,Transport(),'REMINDER')['delivered']==0
