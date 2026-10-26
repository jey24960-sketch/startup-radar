// Synthetic isolated Postgres tests; never connect to the hosted database.
import test,{before,after} from 'node:test';
import assert from 'node:assert/strict';
import {PGlite} from '@electric-sql/pglite';
import {readFile,readdir} from 'node:fs/promises';

const migration='20261026132026_radar_early_announcements.sql';
const id=n=>`00000000-0000-0000-0000-${String(n).padStart(12,'0')}`;
let db;
const rows=async(sql,args=[])=>(await db.query(sql,args)).rows;
async function as(actor,role,fn){
 await rows("select set_config('request.jwt.claim.sub',$1,false)",[actor?id(actor):'']);
 await db.exec(`set role ${role}`);
 try{return await fn();}finally{await db.exec('reset role').catch(()=>{});}
}
const detail=async()=> (await rows('select public.gfc_radar_early_notice($1) value',[id(100)]))[0].value;
const list=async()=> (await rows('select public.gfc_radar_early_notices() value'))[0].value;
const facts=(end='2026-11-04T12:00:00+09:00')=>({
 title:'예비창업자 MVP 제작 지원',organization:'공식 지원기관',deadline_type:'FIXED_DATE',
 application_start_at:'2026-10-29T00:00:00+09:00',application_start_precision:'DATE',
 application_end_at:end,application_end_precision:'DATETIME',official_url:'https://example.org/early',
});
before(async()=>{
 db=await PGlite.create();
 await db.exec(`create schema auth;create role anon;create role authenticated;create role service_role bypassrls;
 create table auth.users(id uuid primary key);
 create function auth.uid() returns uuid language sql stable as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
 grant usage on schema auth to authenticated;grant execute on function auth.uid() to authenticated;`);
 await db.exec(await readFile(new URL('./fixtures/gfc_identity.sql',import.meta.url),'utf8'));
 const folder=new URL('../supabase/migrations/',import.meta.url);
 for(const file of (await readdir(folder)).filter(f=>f.endsWith('.sql')&&f<=migration).sort())await db.exec(await readFile(new URL(file,folder),'utf8'));
 await rows('insert into auth.users values($1),($2),($3)',[id(1),id(2),id(99)]);
 await rows("insert into public.test_gfc_roles values($1,'member'),($2,'external'),($3,'admin')",[id(1),id(2),id(99)]);
 for(let n=1;n<=4;n++){
  await rows("insert into startup_radar.programs(id,canonical_key,title,organization,status,deadline_type,official_url) values($1,$2,$2,'Fixture','OPEN','FIXED_DATE','https://example.org/early')",[id(1000+n),`early-fixture-${n}`]);
  await rows("insert into startup_radar.program_versions(id,program_id,version,content_hash,normalized) values($1,$2,1,$3,'{}')",[id(2000+n),id(1000+n),`early-hash-${n}`]);
 }
 await rows("insert into startup_radar.early_notices(id,week_start,title,summary,published_at,item_count) values($1,'2026-10-26','10월 28일자 중요 모집 사전 안내','중요 모집을 미리 안내합니다.','2026-10-28T12:00:00+09:00',1)",[id(100)]);
 await rows('insert into startup_radar.early_notice_items(notice_id,program_id,program_version_id,display_order,snapshot,stage_codes) values($1,$2,$3,0,$4,$5)',[id(100),id(1001),id(2001),facts(),['STAGE_3']]);
});
after(async()=>await db?.close());

test('deployment starts disabled, DISCOVER owns the existing worker ledger, weekly cap is durable',async()=>{
 const config=(await rows("select value from startup_radar.runtime_settings where key='early_announcements'"))[0].value;
 assert.equal(config.enabled,false);assert.equal(config.active_from,null);
 await rows("insert into startup_radar.worker_executions(id,kind,owner) values($1,'DISCOVER','{}')",[id(500)]);
 assert.equal((await rows("select kind from startup_radar.worker_executions where kind='DISCOVER'"))[0].kind,'DISCOVER');
 await assert.rejects(()=>rows("insert into startup_radar.early_notices(week_start,title,summary,published_at,item_count) values('2026-10-26','Duplicate week','Duplicate week','2026-10-29T00:00:00Z',1)"),/unique|duplicate/);
});

test('DB trigger rejects under-seven-day, unknown, and version-mismatched publication facts',async()=>{
 const insert=(program,version,snapshot)=>rows('insert into startup_radar.early_notice_items(notice_id,program_id,program_version_id,display_order,snapshot) values($1,$2,$3,1,$4)',[id(100),id(program),id(version),snapshot]);
 await assert.rejects(()=>insert(1002,2002,facts('2026-11-04T11:59:59+09:00')),/seven full days/);
 await assert.rejects(()=>insert(1002,2002,{...facts(),deadline_type:'ROLLING'}),/Verified fixed deadline/);
 await assert.rejects(()=>insert(1002,2002,{...facts(),application_end_precision:'UNKNOWN'}),/Verified fixed deadline/);
 await assert.rejects(()=>insert(1002,2002,{...facts(),application_end_at:'not-a-date'}),/Verified fixed deadline/);
 await assert.rejects(()=>insert(1002,2002,{...facts(),application_end_at:'2026-11-04T12:00:00'}),/Verified fixed deadline/);
 await assert.rejects(()=>insert(1002,2002,{...facts(),application_start_at:'2026-11-05T00:00:00+09:00'}),/period is inverted/);
 await assert.rejects(()=>insert(1002,2003,facts()),/does not belong/);
 assert.equal((await rows('select count(*) n from startup_radar.early_notice_items'))[0].n,1);
});

test('member RPC exposes only published facts, respects membership and central visibility',async()=>{
 const article=await as(1,'authenticated',detail);
 assert.equal(article.publication_kind,'EARLY');assert.equal(article.item_count,1);
 assert.equal(article.items[0].facts.title,'예비창업자 MVP 제작 지원');
 assert.deepEqual(article.items[0].stage_fit,[{code:'STAGE_3',label:'MVP·PoC'}]);
 assert.ok(!JSON.stringify(article).includes('chat_id'));assert.ok(!('delivery_state' in article));
 assert.equal((await as(1,'authenticated',list)).total,1);
 await assert.rejects(()=>as(null,'anon',detail),/membership/);
 await assert.rejects(()=>as(2,'authenticated',list),/membership/);
 await assert.rejects(()=>as(1,'authenticated',()=>rows('select chat_id from startup_radar.early_notices')),/permission denied/);
 await rows("update startup_radar.runtime_settings set value=jsonb_set(value,'{mode}','\"PRIVATE\"') where key='radar_visibility'");
 await assert.rejects(()=>as(1,'authenticated',detail),/private/);
 assert.equal((await as(99,'authenticated',detail)).id,id(100));
 await rows("update startup_radar.runtime_settings set value=jsonb_set(value,'{mode}','\"MEMBERS_ONLY\"') where key='radar_visibility'");
 await rows("update startup_radar.early_notices set status='WITHDRAWN',withdrawn_at=now(),withdrawal_reason='Synthetic fixture withdrawal' where id=$1",[id(100)]);
 assert.equal(await as(1,'authenticated',detail),null);assert.equal((await as(1,'authenticated',list)).total,0);
});
