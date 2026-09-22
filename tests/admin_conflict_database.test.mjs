// Real SQL over isolated fixtures; no managed Auth, HTTP or delivery claims.
import test,{before,after} from 'node:test';
import assert from 'node:assert/strict';
import {PGlite} from '@electric-sql/pglite';
import {readFile,readdir} from 'node:fs/promises';
const candidate='20260922143410_radar_admin_business_conflict_http_status.sql';
const names=['gfc_radar_admin_set_operation','gfc_radar_admin_set_visibility',
 'gfc_radar_admin_withdraw_briefing','gfc_radar_admin_restore_briefing'];
const id=n=>`00000000-0000-0000-0000-${String(n).padStart(12,'0')}`;
let db,beforeMetadata,beforeData;
const rows=async(sql,args=[])=>(await db.query(sql,args)).rows;
const metadata=()=>rows(`select oid,proname,proowner,proacl::text,prosecdef,proconfig,prorettype,
 proargtypes::text,proargnames,proargdefaults::text,provolatile,replace(prosrc,chr(13),'') prosrc from pg_proc
 where pronamespace='public'::regnamespace and proname=any($1) order by proname`,[names]);
async function data(){
 const result={};
 for(const table of ['runtime_settings','weekly_briefings','weekly_briefing_items','weekly_announcements','admin_audit'])
  result[table]=(await rows(`select to_jsonb(t) row from startup_radar.${table} t order by to_jsonb(t)::text`)).map(r=>r.row);
 return result;
}
async function as(actor,fn,role='authenticated'){
 await rows("select set_config('request.jwt.claim.sub',$1,true)",[actor?String(actor):'']);
 await db.exec(`set local role ${role}`);
 try{return await fn();}finally{await db.exec('reset role').catch(()=>{});}
}
const call=(name,args)=>rows(`select public.${name}(${args.map((_,i)=>'$'+(i+1)).join(',')}) result`,args);
async function rejects(fn,code){
 await db.exec('savepoint expected_denial');let caught;
 try{await fn();}catch(error){caught=error;}
 await db.exec('rollback to savepoint expected_denial; release savepoint expected_denial');
 assert.ok(caught,'must reject');assert.equal(caught.code,code,caught.message);
}
async function scenario(fn){await db.exec('begin');try{await fn();}finally{await db.exec('rollback; reset role');}}
before(async()=>{
 db=await PGlite.create();
 await db.exec(`create schema auth; create role anon; create role authenticated; create role service_role bypassrls;
 create table auth.users(id uuid primary key);
 create function auth.uid() returns uuid language sql stable as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
 grant usage on schema auth to authenticated; grant execute on function auth.uid() to authenticated;`);
 await db.exec(await readFile(new URL('./fixtures/gfc_identity.sql',import.meta.url),'utf8'));
 const folder=new URL('../supabase/migrations/',import.meta.url);
 for(const file of (await readdir(folder)).filter(f=>f.endsWith('.sql')&&f<candidate).sort())
  await db.exec(await readFile(new URL(file,folder),'utf8'));
 await rows('insert into auth.users values($1),($2)',[id(99),id(1)]);
 await rows("insert into public.test_gfc_roles values($1,'admin'),($2,'member')",[id(99),id(1)]);
 await rows("insert into startup_radar.ingestion_runs(id,status,trigger_type,finished_at) values($1,'SUCCESS','synthetic',now())",[id(10)]);
 await rows(`insert into startup_radar.weekly_briefings(id,week_start,week_end,title,status,published_at,summary,collection_status,ingestion_run_id)
 values($1,'2026-09-21','2026-09-27','Synthetic title','PUBLISHED','2026-09-22T01:00Z','Stored summary','SUCCESS',$2)`,[id(11),id(10)]);
 await rows(`insert into startup_radar.weekly_announcements(briefing_id,chat_id,payload,state,target_kind,receipt,delivered_at)
 values($1,'synthetic-channel','Original delivered message','DELIVERED','OFFICIAL_CHANNEL','{"message_id":42}','2026-09-22T01:01Z')`,[id(11)]);
 beforeMetadata=await metadata();beforeData=await data();
 await db.exec(await readFile(new URL(candidate,folder),'utf8'));
});
after(async()=>{await db?.close();});

test('forward migration changes exactly four explicit errors; metadata, privileges and every stored row stay unchanged',async()=>{
 const after=await metadata();assert.equal(after.length,4);
 assert.deepEqual(after,beforeMetadata.map(row=>({...row,prosrc:row.prosrc.replace("errcode='40001'","errcode='PT409'")})));
 for(const row of after){assert.equal(row.prosrc.includes('40001'),false);assert.equal(row.prosrc.split('PT409').length-1,1);}
 assert.deepEqual(await data(),beforeData);
});

test('stale operation and visibility versions return PT409 once with no additional state or audit writes',()=>scenario(async()=>{
 for(const [name,args] of [[names[0],[false,1,'Synthetic pause']],[names[1],['PUBLIC',1,'Synthetic visibility']]]){
  await as(id(99),()=>call(name,args));
  const confirmed=await data();
  await rejects(()=>as(id(99),()=>call(name,args)),'PT409');
  assert.deepEqual(await data(),confirmed);
 }
 assert.equal((await data()).admin_audit.length,2);
}));

test('repeated hide/restore return PT409 without content, first-date or delivery mutation',()=>scenario(async()=>{
 const original=(await data()).weekly_briefings[0];
 await as(id(99),()=>call(names[2],[id(11),'Synthetic hide']));
 const hidden=await data();
 await rejects(()=>as(id(99),()=>call(names[2],[id(11),'Repeated hide'])),'PT409');
 assert.deepEqual(await data(),hidden);
 await as(id(99),()=>call(names[3],[id(11)]));
 const restored=await data();
 await rejects(()=>as(id(99),()=>call(names[3],[id(11)])),'PT409');
 assert.deepEqual(await data(),restored);
 assert.deepEqual(restored.weekly_briefings,[original]);
 assert.deepEqual(restored.weekly_announcements,beforeData.weekly_announcements);
 assert.deepEqual(restored.weekly_briefing_items,beforeData.weekly_briefing_items);
 assert.equal(restored.admin_audit.length,2);
}));

test('anonymous, unknown identity and member denial remain; no caller gains direct privileges',()=>scenario(async()=>{
 const commands=[[names[0],[false,1,null]],[names[1],['PRIVATE',1,null]],[names[2],[id(11),null]],[names[3],[id(11)]]];
 for(const [actor,role] of [[null,'anon'],[null,'authenticated'],[id(88),'authenticated'],[id(1),'authenticated']])
  for(const [name,args] of commands)await rejects(()=>as(actor,()=>call(name,args),role),'42501');
 assert.deepEqual(await data(),beforeData);
}));

test('missing prerequisite fails before any replacement can create default public grants',async()=>{
 const empty=await PGlite.create();
 try{
  const sql=await readFile(new URL('../supabase/migrations/'+candidate,import.meta.url),'utf8');
  await assert.rejects(empty.exec(sql),/Existing Radar operator-control RPCs are required/);
  await empty.exec('rollback');
  assert.equal((await empty.query("select count(*)::int n from pg_proc where proname like 'gfc_radar_admin_%'")).rows[0].n,0);
 }finally{await empty.close();}
});
