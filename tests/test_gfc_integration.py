import pytest
from uuid import uuid4
from types import SimpleNamespace
from psycopg.types.json import Jsonb
from radar.analysis_cache import extract_cached
from radar.models import TeamProfile,apply_preset
from radar.services import browse
from radar.web import create_app
from radar.auth import authenticated_user
from fastapi.testclient import TestClient
from test_database import db,source,program
from test_web_runtime import context


def test_verified_member_without_radar_team_can_start_immediately(context):
    member=uuid4()
    with context['db'].transaction() as c:c.execute('insert into auth.users values(%s)',(member,))
    context['app'].dependency_overrides[authenticated_user]=lambda:member
    response=context['client'].get('/api/programs?preset=0&recommended=true')
    assert response.status_code==200 and response.json()['total']==1
    assert response.json()['profile']['founder_age'] is None
    created=context['client'].post('/api/teams',json={'preset':0})
    assert created.status_code==201
    assert context['client'].get('/api/me').json()['teams'][0]['id']==created.json()['id']


def test_revoked_gfc_membership_denies_existing_team_and_cached_results(context):
    c=context;client=c['client']
    assert client.get('/api/programs?team_id='+str(c['team']['id'])).status_code==200
    with c['db'].transaction() as dbconn:
        dbconn.execute("insert into public.test_gfc_roles values(%s,'external')",(c['admin'],))
    for path in ['/api/programs','/api/programs/'+str(c['saved']['program_id']),'/api/admin/health']:
        assert client.get(path).status_code==403
    assert client.post('/api/teams',json={'preset':0}).status_code==403
    with c['db'].transaction(c['admin']) as dbconn:
        assert dbconn.execute('select * from startup_radar.feed_snapshots').fetchall()==[]
        assert dbconn.execute('select * from startup_radar.programs').fetchall()==[]


def test_database_pagination_filters_and_profile_cache_invalidation(context):
    c=context;client=c['client'];scope='?team_id='+str(c['team']['id'])
    for i in range(4):
        p=c['program'].model_copy(deep=True);p.title=f'Pagination {i}';p.official_url+=f'/{i}'
        c['db'].save_program(p,c['source'],f'pagination-{i}',p.official_url,{})
    first=client.get('/api/programs'+scope+'&recommended=true&limit=2&offset=0').json()
    second=client.get('/api/programs'+scope+'&recommended=true&limit=2&offset=2').json()
    assert first['total']==second['total']==5
    assert not set(i['id'] for i in first['items']) & set(i['id'] for i in second['items'])
    assert client.get('/api/programs'+scope+'&q=Pagination&limit=2').json()['total']==4
    with c['db'].transaction() as conn:before=conn.execute('select count(*) n from startup_radar.feed_snapshots').fetchone()['n']
    client.get('/api/programs'+scope+'&recommended=true')
    with c['db'].transaction() as conn:assert conn.execute('select count(*) n from startup_radar.feed_snapshots').fetchone()['n']==before
    client.patch('/api/teams/'+str(c['team']['id'])+'/profile',json={'expected_version':1,'changes':{'business_status':'CORPORATION'}})
    assert client.get('/api/programs'+scope+'&recommended=true').json()['total']==0
    assert client.get('/api/programs'+scope+'&eligibility=INELIGIBLE').json()['total']==5


def test_analysis_same_hash_skips_llm_changed_document_reanalyzes(db):
    p=program();s=source(db);detail=SimpleNamespace(text='Stable source evidence')
    class Extractor:
        version='fixture-1'; model='fixture';calls=0
        def extract(self,program,detail,documents,source_id):
            self.calls+=1; return program
    e=Extractor();docs=[{'original_url':'https://example.org/a.hwp','content_hash':'a','extraction_status':'SUCCESS','extracted_text':'A'}]
    first={};extract_cached(db,e,p,detail,docs,s,first)
    second={};extract_cached(db,e,p,detail,docs,s,second)
    assert e.calls==1 and second['cache_hit']
    docs[0]['content_hash']='b';docs[0]['extracted_text']='B'
    extract_cached(db,e,p,detail,docs,s,{})
    assert e.calls==2
    e.version='fixture-2';extract_cached(db,e,p,detail,docs,s,{})
    assert e.calls==3


def test_cors_only_allows_configured_gfc_origin(context):
    c=context['client']
    headers={'Origin':'https://www.gfc-startup.com','Access-Control-Request-Method':'GET','Access-Control-Request-Headers':'authorization'}
    assert c.options('/api/me',headers=headers).headers['access-control-allow-origin']=='https://www.gfc-startup.com'
    headers['Origin']='https://untrusted.example'
    assert 'access-control-allow-origin' not in c.options('/api/me',headers=headers).headers


def test_preferences_before_channel_link_and_cross_team_denial(context):
    path='/api/teams/'+str(context['team']['id'])+'/preferences'
    client=context['client']; preferences={'enabled':False,'digest_enabled':True,'alerts_enabled':False,'reminders_enabled':True}
    assert client.get(path).json()['connected'] is False
    assert client.put(path,json=preferences).status_code==200
    assert client.get(path).json()['preferences']==preferences
    context['app'].dependency_overrides[authenticated_user]=lambda:context['other']
    assert client.get(path).status_code==403
    assert client.put(path,json=preferences).status_code==403
