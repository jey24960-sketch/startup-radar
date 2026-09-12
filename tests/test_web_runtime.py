"""Real PostgreSQL authorization and runtime flows; external delivery is stubbed."""
import os
from uuid import uuid4
from datetime import timedelta
import pytest
from fastapi.testclient import TestClient
from radar.web import create_app
from radar.auth import authenticated_user
from radar.models import TeamProfile,Evidence,Requirement,apply_preset
from radar.recommendations import refresh_recommendations
from radar.notifications import plan_notifications,deliver_pending,recover_batch
from radar.telegram import handle_update
from core.clock import now
from test_database import db,source,program

pytestmark=pytest.mark.skipif(not os.environ.get('TEST_DATABASE_URL'),reason='Explicit ephemeral database required')


@pytest.fixture
def context(db):
    admin,other=uuid4(),uuid4()
    with db.transaction() as c:
        c.execute('truncate startup_radar.telegram_updates,startup_radar.schedule_claims')
        c.execute('insert into auth.users values(%s),(%s)',(admin,other))
        c.execute('insert into startup_radar.admin_users values(%s)',(admin,))
    team=db.create_team('GFC fixture A',admin,apply_preset(TeamProfile(),0))
    other_team=db.create_team('Private fixture B',other,TeamProfile(business_status='CORPORATION'))
    app=create_app(db)
    app.dependency_overrides[authenticated_user]=lambda:admin
    client=TestClient(app)
    s=source(db)
    p=program();p.program_types=['GRANT'];p.evidence_complete=True;p.benefit_summary='Fixture mentoring benefit'
    p.application_end_at=now()+timedelta(days=7)
    p.requirements=[Requirement(key='business_status',operator='EQ',value='PRE_BUSINESS',certain=True,
        evidence=[Evidence(source_id=str(s),text='예비창업자만 신청 가능',method='MANUAL',verified=True,confidence=1)])]
    saved=db.save_program(p,s,'first',p.official_url,{},'Fixture only')
    return dict(db=db,admin=admin,other=other,team=team,other_team=other_team,source=s,program=p,saved=saved,app=app,client=client)


def test_anonymous_cannot_read_private_endpoints(context):
    client=TestClient(create_app(context['db']))
    for route in ['/api/me','/api/programs','/api/admin/health','/api/admin/notifications']:
        assert client.get(route).status_code==401
    config=client.get('/api/public-config')
    assert config.status_code==200 and len(config.json()['presets'])==5
    assert 'DATABASE_URL' not in config.text and 'frame-ancestors' in config.headers['content-security-policy']
    assert client.get('/static/app.js').status_code==404
    assert client.get('/static/index.html').status_code==404
    assert TestClient(create_app(context['db'],preview=True)).get('/static/app.js').headers['content-type'].startswith('text/javascript')


def test_shared_auth_identity_does_not_grant_radar_membership(context):
    outsider=uuid4()
    with context['db'].transaction() as c:
        c.execute('insert into auth.users values(%s)',(outsider,))
        c.execute("insert into public.test_gfc_roles values(%s,'external')",(outsider,))
    context['app'].dependency_overrides[authenticated_user]=lambda:outsider
    client=context['client']
    assert client.get('/api/me').json()=={'user_id':str(outsider), 'teams':[], 'is_admin':False}
    assert client.get('/api/programs?preset=0').status_code==403
    assert client.get('/api/admin/health').status_code==403
    assert client.get('/api/teams/'+str(context['team']['id'])+'/profile').status_code==403


def test_stage_zero_browsing_and_evidence(context):
    client=context['client'];r=client.get('/api/programs?preset=0&recommended=true')
    assert r.status_code==200 and r.json()['total']==1
    assert r.json()['profile']['founder_age'] is None
    item=r.json()['items'][0];assert item['eligibility']['status']=='ELIGIBLE'
    detail=client.get('/api/programs/'+item['id']+'?preset=0').json()
    assert all(key in detail for key in ['facts','eligibility','recommendation','versions','documents'])
    assert detail['eligibility']['matched_requirements'][0]['evidence'][0]['text']=='예비창업자만 신청 가능'


def test_program_detail_history_keeps_version_facts_and_document_failures(context):
    c=context; original=c['program']; updated=original.model_copy(deep=True)
    updated.application_end_at+=timedelta(days=7)
    saved=c['db'].save_program(updated,c['source'],'first',updated.official_url,{},'Updated fixture',documents=[{
        'original_url':'https://example.org/notice.hwp','filename':'공고문.hwp','content_hash':'fixture-broken-hwp',
        'fetch_status':'SUCCESS','extraction_status':'FAILED','error_kind':'DOCUMENT_PARSE'}])
    path='/api/programs/'+str(saved['program_id'])+'?preset=0'
    current=c['client'].get(path).json()
    previous=c['client'].get(path+'&version_id='+str(c['saved']['version_id'])).json()
    assert [v['version'] for v in current['versions']]==[2,1]
    assert current['documents'][0]['extraction_status']=='FAILED'
    assert previous['documents']==[]
    assert current['facts']['application_end_at']!=previous['facts']['application_end_at']
    assert previous['facts']['application_end_at']==original.model_dump(mode='json')['application_end_at']
    assert 'application_end_at' in current['changes'][0]['changed_fields']
    assert previous['eligibility']['matched_requirements'][0]['key']=='business_status'
    other=updated.model_copy(deep=True);other.official_url+='/other'
    foreign=c['db'].save_program(other,c['source'],'other',other.official_url,{},'Different program')
    assert c['client'].get(path+'&version_id='+str(foreign['version_id'])).status_code==404


def test_cross_team_profile_read_write_and_history_denied(context):
    client=context['client'];other=str(context['other_team']['id'])
    assert client.get('/api/teams/'+other+'/profile').status_code==403
    assert client.patch('/api/teams/'+other+'/profile',json={'expected_version':1,'changes':{'region':'Seoul'}}).status_code==403
    assert client.get('/api/teams/'+other+'/history').status_code==403
    context['app'].dependency_overrides[authenticated_user]=lambda:context['other']
    assert client.get('/api/admin/health').status_code==403
    assert client.get('/api/admin/failures').status_code==403
    assert client.get('/api/admin/notifications').status_code==403
    assert client.get('/api/programs?team_id='+other).json()['items'][0]['eligibility']['status']=='INELIGIBLE'


def test_progressive_profile_versions_and_stale_write(context):
    path='/api/teams/'+str(context['team']['id'])+'/profile';client=context['client']
    r=client.patch(path,json={'expected_version':1,'changes':{'region':'Seoul','founder_age':27}})
    assert r.status_code==200 and r.json()['version']==2
    assert client.patch(path,json={'expected_version':1,'changes':{'region':'Busan'}}).status_code==400
    result=client.patch(path,json={'expected_version':2,'preset':3}).json()
    assert result['profile']['region']=='Seoul' and result['profile']['founder_age']==27
    assert result['profile']['business_status'] is None


def test_health_and_missing_dispatch_config_visible(context,monkeypatch):
    monkeypatch.delenv('RADAR_GITHUB_TOKEN',raising=False)
    client=context['client'];r=client.post('/api/admin/jobs',json={'kind':'INGEST'})
    assert r.status_code==202 and r.json()['state']=='FAILED'
    result=client.get('/api/admin/health').json()
    assert result['successful_sources']==0 and result['jobs'][0]['state']=='FAILED'
    assert result['tracked_source_success_rate']==0


def test_job_cancellation_endpoint_requires_admin_and_records_result(context):
    with context['db'].transaction() as c:
        job=c.execute("insert into startup_radar.job_requests(kind) values('INGEST') returning id").fetchone()['id']
    path='/api/admin/jobs/'+str(job)+'/cancel'
    context['app'].dependency_overrides[authenticated_user]=lambda:context['other']
    assert context['client'].post(path,json={'note':'Retire fixture request'}).status_code==403
    context['app'].dependency_overrides[authenticated_user]=lambda:context['admin']
    result=context['client'].post(path,json={'note':'Retire fixture request'})
    assert result.status_code==200 and result.json()['state']=='CANCELLED'


def test_webhook_rejects_forgery_and_nonobjects(context,monkeypatch):
    monkeypatch.setenv('TELEGRAM_WEBHOOK_SECRET','fixture-only-secret')
    assert context['client'].post('/telegram/webhook',json={'update_id':1}).status_code==403
    r=context['client'].post('/telegram/webhook',json=[],headers={'X-Telegram-Bot-Api-Secret-Token':'fixture-only-secret'})
    assert r.status_code==400


class Transport:
    def __init__(self,state='DELIVERED'):self.messages=[];self.state=state
    def send(self,chat,text):
        self.messages.append((chat,text))
        return {'state':self.state,'receipt':{'message_id':len(self.messages)}} if self.state=='DELIVERED' else {'state':self.state,'error':'fixture'}


def telegram_admin(ctx):
    with ctx['db'].transaction() as c:
        c.execute('insert into startup_radar.telegram_admins(telegram_user_id,user_id,selected_team_id) values(%s,%s,%s)',('123',ctx['admin'],ctx['team']['id']))


def update(n,text,sender=123):return {'update_id':n,'message':{'from':{'id':sender},'chat':{'id':456},'text':text}}


def test_telegram_auth_idempotence_real_status_and_profile(context):
    telegram_admin(context);transport=Transport();db=context['db']
    assert handle_update(db,update(1,'/run',999),transport)['state']=='IGNORED'
    assert not transport.messages
    assert handle_update(db,update(2,'/status'),transport)['state']=='COMPLETED'
    assert '아직 수집 실행 기록이 없습니다' in transport.messages[-1][1]
    assert handle_update(db,update(2,'/status'),transport)['state']=='DUPLICATE'
    assert len(transport.messages)==1
    assert handle_update(db,update(3,'/stage 3'),transport)['state']=='COMPLETED'
    with db.transaction() as c:
        row=c.execute('select * from startup_radar.team_profiles where team_id=%s',(context['team']['id'],)).fetchone()
        assert row['version']==2 and row['profile']['product_stage']=='MVP' and row['profile']['business_status'] is None
    assert handle_update(db,update(4,'/stop'),transport)['state']=='COMPLETED'
    with db.transaction() as c:assert c.execute("select value from startup_radar.runtime_settings where key='scheduling'").fetchone()['value']['enabled'] is False


def test_digest_receipt_matches_all_grouped_items(context):
    db=context['db'];p=context['program'].model_copy(deep=True);p.title+=' age requirement';p.official_url+='/age'
    p.requirements.append(Requirement(key='founder_age',operator='LTE',value=39,certain=True,
        evidence=[Evidence(source_id=str(context['source']),text='대표자 만 39세 이하',method='MANUAL',verified=True,confidence=1)]))
    db.save_program(p,context['source'],'second',p.official_url,{},'Age fixture')
    with db.transaction() as c:c.execute('insert into startup_radar.telegram_subscriptions(team_id,chat_id) values(%s,%s)',(context['team']['id'],'fixture-chat'))
    refresh_recommendations(db)
    assert plan_notifications(db,'DIGEST')==2
    assert plan_notifications(db,'DIGEST')==0
    transport=Transport();result=deliver_pending(db,transport,'DIGEST')
    assert result['delivered']==2 and len(transport.messages)==1
    assert '지원 가능 1 · 추가 정보 필요 1' in transport.messages[0][1]
    assert '지원 가능 여부: 추가 정보 필요' in transport.messages[0][1]
    with db.transaction() as c:
        rows=c.execute('select delivery_receipts,delivered_at from startup_radar.notification_items').fetchall()
        assert all(r['delivered_at'] and r['delivery_receipts']==[{'message_id':1}] for r in rows)


def subscribe(context):
    with context['db'].transaction() as c:c.execute('insert into startup_radar.telegram_subscriptions(team_id,chat_id,high_fit_threshold) values(%s,%s,0)',(context['team']['id'],'fixture-chat'))
    refresh_recommendations(context['db'])


def test_pending_profile_change_cancels_stale_delivery(context):
    db=context['db'];subscribe(context);assert plan_notifications(db,'REMINDER')==1
    db.save_profile(context['team']['id'],TeamProfile(business_status='CORPORATION'),context['admin'],1)
    transport=Transport();result=deliver_pending(db,transport,'REMINDER')
    assert result['cancelled']==1 and not transport.messages


def test_uncertain_delivery_never_automatically_retried(context):
    db=context['db'];subscribe(context);plan_notifications(db,'REMINDER')
    transport=Transport('UNCERTAIN')
    assert deliver_pending(db,transport,'REMINDER')['failed']==1
    assert deliver_pending(db,transport,'REMINDER')['delivered']==0 and len(transport.messages)==1
    with db.transaction() as c:batch=c.execute('select * from startup_radar.notification_batches').fetchone()
    with pytest.raises(ValueError):recover_batch(db,batch['id'],'RETRY_REJECTED','checked fixture',context['admin'])
    assert recover_batch(db,batch['id'],'CONFIRM_NOT_SENT','Confirmed absent in fixture chat',context['admin'])['state']=='PENDING'
    assert deliver_pending(db,Transport(),'REMINDER')['delivered']==1


def test_high_fit_daily_cap_and_material_update_once(context):
    db=context['db'];s=context['source'];p=context['program']
    for i in range(3):
        other=p.model_copy(deep=True);other.title+=str(i);other.official_url+='/'+str(i)
        db.save_program(other,s,str(i),other.official_url,{},'More fixtures')
    subscribe(context)
    assert plan_notifications(db,'HIGH_FIT')==2
    assert plan_notifications(db,'HIGH_FIT')==0
    deliver_pending(db,Transport(),'HIGH_FIT')
    assert plan_notifications(db,'HIGH_FIT')==0
    future=now()+timedelta(days=1)
    assert plan_notifications(db,'HIGH_FIT',future)==2
    assert plan_notifications(db,'HIGH_FIT',future)==0


def test_admin_trace_links_profile_program_and_notification(context):
    db=context['db'];subscribe(context);plan_notifications(db,'REMINDER')
    with db.transaction() as c:rec=c.execute('select recommendation_id from startup_radar.notification_items').fetchone()['recommendation_id']
    r=context['client'].get('/api/admin/trace/'+str(rec))
    assert r.status_code==200
    trace=r.json();assert trace['profile_version']['version']==1 and trace['provenance'] and trace['notifications']


def test_material_update_can_alert_once(context):
    db=context['db'];subscribe(context)
    assert plan_notifications(db,'HIGH_FIT')==1
    assert deliver_pending(db,Transport(),'HIGH_FIT')['delivered']==1
    assert plan_notifications(db,'HIGH_FIT')==0
    p=context['program'];p.application_end_at+=timedelta(days=5)
    saved=db.save_program(p,context['source'],'first',p.official_url,{},'Extended fixture')
    assert saved['event']=='UPDATE'
    refresh_recommendations(db)
    assert plan_notifications(db,'HIGH_FIT')==1 and plan_notifications(db,'HIGH_FIT')==0


def test_deadline_expiration_cancels_queued_reminder(context):
    db=context['db'];subscribe(context);assert plan_notifications(db,'REMINDER')==1
    transport=Transport();result=deliver_pending(db,transport,'REMINDER',at=now()+timedelta(days=8))
    assert result['cancelled']==1 and not transport.messages
