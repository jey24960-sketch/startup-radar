import test,{before,after} from 'node:test';
import assert from 'node:assert/strict';
import {PGlite} from '@electric-sql/pglite';
import {readFile,readdir} from 'node:fs/promises';
const candidate='20260922150853_weekly_item_sort_identity.sql';
const id=n=>`00000000-0000-0000-0000-${String(n).padStart(12,'0')}`;
let db,previous,metadataBefore,dataBefore;
const rows=async(sql,args=[])=>(await db.query(sql,args)).rows;
const metadata=async()=> (await rows("select oid,proowner,proacl::text,proconfig,prosecdef,provolatile from pg_proc where oid='public.gfc_radar_weekly_briefing(uuid)'::regprocedure"))[0];
async function data(){const result={};for(const table of ['weekly_briefings','weekly_briefing_items','weekly_announcements','admin_audit','runtime_settings'])result[table]=await rows(`select to_jsonb(t) row from startup_radar.${table} t order by to_jsonb(t)::text`);return result;}
async function as(actor,role,fn){await rows("select set_config('request.jwt.claim.sub',$1,false)",[actor?id(actor):'']);await db.exec(`set role ${role}`);try{return await fn();}finally{await db.exec('reset role').catch(()=>{});}}
const detail=async()=> (await rows('select public.gfc_radar_weekly_briefing($1) value',[id(800)]))[0].value;
before(async()=>{
 db=await PGlite.create();
 await db.exec(`create schema auth;create role anon;create role authenticated;create role service_role bypassrls;
 create table auth.users(id uuid primary key);
 create function auth.uid() returns uuid language sql stable as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
 grant usage on schema auth to authenticated;grant execute on function auth.uid() to authenticated;`);
 await db.exec(await readFile(new URL('./fixtures/gfc_identity.sql',import.meta.url),'utf8'));
 const folder=new URL('../supabase/migrations/',import.meta.url);
 for(const file of (await readdir(folder)).filter(f=>f.endsWith('.sql')&&f<candidate).sort())await db.exec(await readFile(new URL(file,folder),'utf8'));
 await rows('insert into auth.users values($1),($2),($3)',[id(1),id(2),id(99)]);
 await rows("insert into public.test_gfc_roles values($1,'member'),($2,'external'),($3,'admin')",[id(1),id(2),id(99)]);
 await rows("insert into startup_radar.ingestion_runs(id,status,trigger_type,finished_at) values($1,'SUCCESS','synthetic',now())",[id(700)]);
 await rows(`insert into startup_radar.weekly_briefings(id,week_start,week_end,title,status,published_at,summary,collection_status,ingestion_run_id,item_count,new_count)
 values($1,'2026-09-21','2026-09-27','Stored title','PUBLISHED','2026-09-22T01:00Z','Stored summary','SUCCESS',$2,65,65)`,[id(800),id(700)]);
 for(let n=65;n>=1;n--){
  await rows("insert into startup_radar.programs(id,canonical_key,title,organization,status,deadline_type,official_url) values($1,$2,$2,'Synthetic','OPEN','FIXED_DATE','https://example.invalid')",[id(1000+n),`synthetic-${n}`]);
  await rows("insert into startup_radar.program_versions(id,program_id,version,content_hash,normalized) values($1,$2,1,$3,'{}')",[id(2000+n),id(1000+n),`hash-${n}`]);
  await rows(`insert into startup_radar.weekly_briefing_items(briefing_id,program_id,program_version_id,change_type,display_order,snapshot,material_hash,relevance_status,stage_codes)
  values($1,$2,$3,'NEW',$4,$5,$6,'GFC_RELEVANT',$7)`,[id(800),id(1000+n),id(2000+n),n,{title:`Synthetic ${n}`},`material-${n}`,n===65?['STAGE_0','STAGE_4']:n===64?[]:['STAGE_4']]);
 }
 await rows("insert into startup_radar.weekly_announcements(briefing_id,chat_id,payload,state,target_kind) values($1,'synthetic','Original message','DELIVERED','OFFICIAL_CHANNEL')",[id(800)]);
 metadataBefore=await metadata();dataBefore=await data();previous=await as(1,'authenticated',detail);
 await db.exec(await readFile(new URL(candidate,folder),'utf8'));
});
after(async()=>await db?.close());
test('additive contract returns all 65 stable IDs/orders, preserves snapshots, permissions and stored rows',async()=>{
 const next=await as(1,'authenticated',detail);
 assert.equal(next.items.length,65);assert.equal(new Set(next.items.map(x=>x.program_id)).size,65);
 assert.deepEqual(next.items.map(x=>x.program_id),Array.from({length:65},(_,i)=>id(1001+i)));
 assert.ok(next.items.every(x=>Number.isInteger(x.display_order)));
 assert.deepEqual(next.items.at(-1).stage_fit.map(s=>s.code),['STAGE_0','STAGE_4']);
 const stripped=next.items.map(({program_id,display_order,...item})=>item).sort((a,b)=>a.facts.title.localeCompare(b.facts.title));
 assert.deepEqual(stripped,previous.items.toSorted((a,b)=>a.facts.title.localeCompare(b.facts.title)));
 assert.deepEqual({...next,items:[]},{...previous,items:[]});
 assert.deepEqual(await metadata(),metadataBefore);assert.deepEqual(await data(),dataBefore);
});
test('existing PUBLIC/MEMBERS_ONLY/PRIVATE and hidden/draft checks remain authoritative',async()=>{
 for(const [actor,role] of [[null,'anon'],[2,'authenticated'],[3,'authenticated']])await assert.rejects(()=>as(actor,role,detail),/membership/);
 for(const [mode,allowed] of [['PUBLIC',true],['PRIVATE',false],['MEMBERS_ONLY',false]]){
  await rows("update startup_radar.runtime_settings set value=jsonb_set(value,'{mode}',to_jsonb($1::text)) where key='radar_visibility'",[mode]);
  if(allowed)assert.equal((await as(null,'anon',detail)).items.length,65);
  else await assert.rejects(()=>as(null,'anon',detail),/private|membership/);
 }
 await rows('update startup_radar.weekly_briefings set withdrawn_at=now(),withdrawn_by=$1 where id=$2',[id(99),id(800)]);
 assert.equal(await as(1,'authenticated',detail),null);assert.equal(await as(99,'authenticated',detail),null);
 await rows("update startup_radar.weekly_briefings set withdrawn_at=null,withdrawn_by=null,status='DRAFT',published_at=null where id=$1",[id(800)]);
 assert.equal(await as(1,'authenticated',detail),null);
});
