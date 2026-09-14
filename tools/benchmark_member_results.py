"""Reproducible synthetic load measurements; refuses non-local/unmarked databases."""
import argparse
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import hashlib
import math
import os
from pathlib import Path
import platform
import subprocess
from time import perf_counter
import tracemalloc
from unittest.mock import patch
from uuid import uuid4

import psycopg
import httpx
import requests
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb
from core.clock import now
from radar.database import Database
from radar.member_results import refresh_member_results
from radar.models import Program, TeamProfile, Evidence, Requirement


def require_test_database(db):
    config=conninfo_to_dict(db.url)
    if config.get('host') not in ('127.0.0.1','localhost','::1') or config.get('service') or (
        config.get('hostaddr') and config['hostaddr'] not in ('127.0.0.1','::1')):
        raise ValueError('Only a local ephemeral benchmark database is permitted')
    with db.transaction() as c:
        marker=c.execute('select value from public.radar_test_marker').fetchone()
        if not marker or marker['value']!='ephemeral-test-only':
            raise ValueError('Refusing to reset an unmarked database')


def seed(db,teams_count):
    require_test_database(db)
    teams=[];programs=[]
    with db.transaction() as c:
        c.execute('truncate auth.users,startup_radar.teams,startup_radar.sources,startup_radar.programs,startup_radar.ingestion_runs,startup_radar.notification_runs cascade')
        c.execute('truncate startup_radar.worker_executions,startup_radar.schedule_claims cascade')
        c.execute("update startup_radar.member_read_state set generation='UNINITIALIZED',state='PENDING',started_at=null,finished_at=null,last_successful_refresh_at=null,last_failure_at=null,last_failure_reason=null,error_kind=null")
        for i in range(teams_count):
            user_id,team_id=uuid4(),uuid4()
            profile=TeamProfile(business_status='PRE_BUSINESS' if i%2 else 'CORPORATION',founder_age=22+i%35,
                student_status=None if i%3 else True,region='Seoul' if i%2 else 'Busan',product_stage='MVP' if i%3 else 'IDEA')
            c.execute('insert into auth.users(id) values(%s)',(user_id,))
            c.execute("insert into public.test_gfc_roles values(%s,'member')",(user_id,))
            c.execute('insert into startup_radar.teams(id,name) values(%s,%s)',(team_id,f'SYNTHETIC team {i}'))
            c.execute("insert into startup_radar.team_members(team_id,user_id,role) values(%s,%s,'OWNER')",(team_id,user_id))
            c.execute('insert into startup_radar.team_profiles(team_id,profile) values(%s,%s)',(team_id,Jsonb(profile.model_dump(mode='json'))))
            teams.append({'id':team_id,'user':user_id})
        for i in range(57):
            pid=uuid4();versions=3 if i<21 else 2
            evidence=Evidence(text='SYNTHETIC: founder must be 39 or younger.',method='MANUAL',verified=True,confidence=1)
            program=Program(title=f'SYNTHETIC support program {i}',organization='Synthetic fixture only',
                official_url=f'https://example.invalid/benchmark/{i}',application_url=f'https://example.invalid/apply/{i}',
                program_types=['GRANT' if i%2 else 'WORKSPACE'],application_end_at=now()+timedelta(days=3+i),
                deadline_type='FIXED_DATE',application_end_precision='DATETIME',evidence_complete=i%5!=0,
                applicant_summary='SYNTHETIC benchmark evidence. '*25,benefit_summary='Synthetic mentoring and support.',
                requirements=[Requirement(key='founder_age',operator='LTE',value=39,certain=True,evidence=[evidence])])
            c.execute("insert into startup_radar.programs(id,canonical_key,title,organization,program_types,status,deadline_type,official_url,application_end_at) values(%s,%s,%s,%s,%s,'OPEN','FIXED_DATE',%s,%s)",
                (pid,str(pid),program.title,program.organization,program.program_types,program.official_url,program.application_end_at))
            for version in range(1,versions+1):
                vid=uuid4()
                c.execute('insert into startup_radar.program_versions(id,program_id,version,content_hash,normalized,raw_text,evidence_complete,last_observed_at) values(%s,%s,%s,%s,%s,%s,%s,now())',
                    (vid,pid,version,str(vid),Jsonb(program.model_dump(mode='json')),'Synthetic source evidence. '*40,program.evidence_complete))
            c.execute('update startup_radar.programs set current_version_id=%s where id=%s',(vid,pid))
            programs.append({'id':pid,'version_id':vid,'version':versions,'facts':program.model_dump(mode='json')})
    return teams,programs


def measure_refresh(db):
    counters={'connections':0,'transactions':0,'queries':0,'http_attempts':0,'batch_write_calls':0}
    transaction=db.transaction;connect=psycopg.connect
    class CountedConnection:
        def __init__(self,c):self.connection=c
        def execute(self,*args,**kwargs):
            counters['queries']+=1
            return self.connection.execute(*args,**kwargs)
        def __getattr__(self,key):return getattr(self.connection,key)
        @contextmanager
        def cursor(self,*args,**kwargs):
            with self.connection.cursor(*args,**kwargs) as cursor:
                class CountedCursor:
                    def executemany(self,query,params):
                        rows=list(params)
                        counters['queries']+=len(rows)
                        counters['batch_write_calls']+=1
                        return cursor.executemany(query,rows)
                yield CountedCursor()
    @contextmanager
    def counted_transaction(*args,**kwargs):
        counters['transactions']+=1
        with transaction(*args,**kwargs) as c:yield CountedConnection(c)
    def counted_connect(*args,**kwargs):
        counters['connections']+=1
        return connect(*args,**kwargs)
    def reject_http(*args,**kwargs):
        counters['http_attempts']+=1
        raise AssertionError('A deterministic member refresh attempted external HTTP')
    tracemalloc.start();started=perf_counter()
    try:
        with patch.object(db,'transaction',counted_transaction),patch('psycopg.connect',counted_connect), \
             patch.object(httpx.Client,'send',reject_http),patch.object(httpx.AsyncClient,'send',reject_http), \
             patch.object(requests.sessions.Session,'send',reject_http):
            result=refresh_member_results(db)
        if counters['http_attempts']:raise AssertionError('Unexpected HTTP attempts during refresh')
        duration=perf_counter()-started
        _,peak=tracemalloc.get_traced_memory()
    finally:tracemalloc.stop()
    return {**result,**counters,'duration_ms':round(duration*1000,2),'python_heap_peak_bytes':peak,
        'rows_evaluated':result['computed'],'result_rows_written':result['computed'],
        'cache_hit_rate':result['reused']/max(1,result['computed']+result['reused']),
        'ai_calls':0,'ai_calls_basis':'deterministic evaluator; provider HTTP transports guarded',
        'tracemalloc_enabled':True,'query_count_excludes_connection_setup':True}


def rpc_latencies(db,teams,samples,concurrency=1):
    def read(i):
        team=teams[i%len(teams)];start=perf_counter()
        with db.transaction(team['user']) as c:
            result=c.execute('select public.gfc_radar_programs(p_team_id=>%s,p_recommended=>%s,p_program_type=>%s,p_limit=>20) result',
                (team['id'],i%2==0,'WORKSPACE' if i%3==0 else None)).fetchone()['result']
            if result.get('calculation',{}).get('state')!='READY':raise AssertionError('Benchmark read is not fully calculated')
        return (perf_counter()-start)*1000
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        measured=list(pool.map(read,range(samples)))
    ordered=sorted(measured)
    return {'samples':samples,'concurrency':concurrency,'p50_ms':round(ordered[math.ceil(samples*.5)-1],2),
        'p95_ms':round(ordered[math.ceil(samples*.95)-1],2),'p99_ms':round(ordered[math.ceil(samples*.99)-1],2),
        'min_ms':round(min(ordered),2),'max_ms':round(max(ordered),2),
        'includes_connection_and_auth_context':True,'transport':'local native PostgreSQL, not production HTTP'}


def footprint(db):
    with db.transaction() as c:
        return c.execute("select (select count(*) from startup_radar.member_program_results) member_result_rows, "
            "(select count(*) from startup_radar.program_versions) program_versions, "
            "(select count(*) from startup_radar.notification_batches) notification_batches, "
            "pg_total_relation_size('startup_radar.member_program_results') member_result_storage_bytes").fetchone()


def benchmark(db,output,sizes,samples,concurrency=1):
    require_test_database(db)
    with db.transaction() as c:postgres=c.execute('select version() version').fetchone()['version']
    report={'purpose':'SYNTHETIC_NON_PRODUCTION_LOAD','at':now().isoformat(),'platform':platform.platform(),
        'python':platform.python_version(),'postgres':postgres,'cpu_count':os.cpu_count(),
        'base_git_revision':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'code_hashes':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in
            [Path('radar/database.py'),Path('radar/member_results.py'),Path(__file__),*sorted(Path('supabase/migrations').glob('*.sql'))]},
        'memory_measurement':'Python tracemalloc heap only, not PostgreSQL or process RSS',
        'scenarios':[]}
    for count in sizes:
        teams,programs=seed(db,count)
        scenario={'teams':count,'current_programs':len(programs),'initial':footprint(db)}
        for label in ('cold','warm'):
            scenario[label]=measure_refresh(db)
            print(json.dumps({'teams':count,'phase':label,**scenario[label]}),flush=True)
        with db.transaction(teams[0]['user']) as c:
            c.execute('select public.gfc_radar_update_profile(%s,1,%s)',(teams[0]['id'],Jsonb({'region':'Incheon'})))
        scenario['one_profile_changed']=measure_refresh(db)
        program=programs[0];vid=uuid4()
        with db.transaction() as c:
            facts={**program['facts'],'benefit_summary':'Synthetic changed benefit.'}
            c.execute('insert into startup_radar.program_versions(id,program_id,version,content_hash,normalized,raw_text,evidence_complete,last_observed_at) values(%s,%s,%s,%s,%s,%s,%s,now())',
                (vid,program['id'],program['version']+1,str(vid),Jsonb(facts),'Synthetic changed evidence',facts['evidence_complete']))
            c.execute('update startup_radar.programs set current_version_id=%s where id=%s',(vid,program['id']))
        scenario['one_program_changed']=measure_refresh(db)
        scenario['rpc']=rpc_latencies(db,teams,samples)
        if concurrency>1:scenario['rpc_concurrent']=rpc_latencies(db,teams,samples,concurrency)
        scenario['final']=footprint(db)
        if scenario['final']['notification_batches']!=0:raise AssertionError('Benchmark created notification work')
        report['scenarios'].append(scenario)
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'teams':count,'rpc':scenario['rpc'],'final':scenario['final']}),flush=True)
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--teams',type=int,nargs='+',default=[3,100,1000])
    parser.add_argument('--samples',type=int,default=60)
    parser.add_argument('--reads-only',action='store_true')
    parser.add_argument('--concurrency',type=int,default=1)
    args=parser.parse_args()
    if any(n<1 or n>1000 for n in args.teams) or not 20<=args.samples<=1000 or not 1<=args.concurrency<=20:parser.error('Bounded team/sample/concurrency range required')
    url=os.environ.get('TEST_DATABASE_URL')
    if not url:parser.error('Explicit TEST_DATABASE_URL required')
    db=Database(url)
    if args.reads_only:
        require_test_database(db)
        with db.transaction() as c:
            teams=c.execute("select t.id,m.user_id as user from startup_radar.teams t join startup_radar.team_members m on m.team_id=t.id where t.name like 'SYNTHETIC team %%' and m.role='OWNER' order by t.id").fetchall()
        if not teams:raise ValueError('No synthetic benchmark fixture found')
        before=footprint(db)
        result={'purpose':'EXISTING_SYNTHETIC_FIXTURE_READ_ONLY','teams':len(teams),
            'rpc':rpc_latencies(db,teams,args.samples,args.concurrency),'footprint':footprint(db)}
        if result['footprint']!=before:raise AssertionError('Read-only measurement changed table footprint')
        args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result),flush=True)
    else:
        benchmark(db,args.output,args.teams,args.samples,args.concurrency)


if __name__=='__main__':main()
