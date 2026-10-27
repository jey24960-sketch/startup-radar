// Isolated real PostgreSQL semantics; never connects to production.
import test,{before,after} from 'node:test';
import assert from 'node:assert/strict';
import {PGlite} from '@electric-sql/pglite';
import {readFile,readdir} from 'node:fs/promises';

const migration='20261026185314_radar_review_appendix.sql';
const id=n=>`00000000-0000-0000-0000-${String(n).padStart(12,'0')}`;
const at='2026-10-27T09:00:00+09:00';
let db,previousRpc,previousCorrectionAcl,previousRows;
const rows=async(sql,args=[])=>(await db.query(sql,args)).rows;
const metadata=async(name)=>(await rows('select proowner,proacl::text,proconfig,prosecdef from pg_proc where oid=$1::regprocedure',[name]))[0];
async function as(actor,role,fn){
 await rows("select set_config('request.jwt.claim.sub',$1,false)",[actor?id(actor):'']);
 await db.exec(`set role ${role}`);
 try{return await fn();}finally{await db.exec('reset role').catch(()=>{});}
}
const facts=(n,review=false,end='2026-11-20T17:00:00+09:00')=>({title:`창업 지원 후보 ${n}`,organization:'공식 기관',
 official_url:`https://example.invalid/${n}`,deadline_type:'FIXED_DATE',application_end_at:end,
 application_end_precision:'DATETIME',...(review?{review_note:'구체적인 지원 범위를 공식 모집요강에서 확인해 주세요.'}:{})});
async function briefing(n){
 await rows(`insert into startup_radar.weekly_briefings(id,week_start,week_end,title,summary,status,collection_status,ingestion_run_id)
 values($1,date '2026-10-26'+($2::int*7),date '2026-11-01'+($2::int*7),'검증용 주간 공지','검증용 요약','DRAFT','SUCCESS',$3)`,[id(800+n),n,id(700)]);
 return id(800+n);
}
const insert=async(b,n,status,order,snapshot=facts(n,status==='REVIEW_REQUIRED'))=>rows(`
 insert into startup_radar.weekly_briefing_items(briefing_id,program_id,program_version_id,change_type,display_order,snapshot,material_hash,relevance_status)
 values($1,$2,$3,'NEW',$4,$5,$6,$7)`,[b,id(1000+n),id(2000+n),order,snapshot,`material-${n}`,status]);
const publish=b=>rows("update startup_radar.weekly_briefings set status='PUBLISHED',published_at=$2,item_count=(select count(*) from startup_radar.weekly_briefing_items where briefing_id=$1),new_count=(select count(*) from startup_radar.weekly_briefing_items where briefing_id=$1 and change_type='NEW') where id=$1",[b,at]);
const detail=async(b)=>(await rows('select public.gfc_radar_weekly_briefing($1) value',[b]))[0].value;

before(async()=>{
 db=await PGlite.create();
 await db.exec(`create schema auth;create role anon;create role authenticated;create role service_role bypassrls;
 create table auth.users(id uuid primary key);
 create function auth.uid() returns uuid language sql stable as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
 grant usage on schema auth to authenticated;grant execute on function auth.uid() to authenticated;`);
 await db.exec(await readFile(new URL('./fixtures/gfc_identity.sql',import.meta.url),'utf8'));
 const folder=new URL('../supabase/migrations/',import.meta.url);
 for(const file of (await readdir(folder)).filter(f=>f.endsWith('.sql')&&f<migration).sort())await db.exec(await readFile(new URL(file,folder),'utf8'));
 await rows('insert into auth.users values($1),($2),($3)',[id(1),id(2),id(99)]);
 await rows("insert into public.test_gfc_roles values($1,'member'),($2,'external'),($3,'admin')",[id(1),id(2),id(99)]);
 await rows("insert into startup_radar.ingestion_runs(id,status,trigger_type) values($1,'SUCCESS','synthetic')",[id(700)]);
 for(let n=1;n<=10;n++){
  await rows("insert into startup_radar.programs(id,canonical_key,title,organization,status,deadline_type,official_url) values($1,$2,$2,'Fixture','OPEN','FIXED_DATE','https://example.invalid')",[id(1000+n),`review-test-${n}`]);
  await rows("insert into startup_radar.program_versions(id,program_id,version,content_hash,normalized) values($1,$2,1,$3,'{}')",[id(2000+n),id(1000+n),`hash-${n}`]);
 }
 const old=await briefing(-1);await insert(old,1,'GFC_RELEVANT',0,facts(1));
 await rows("update startup_radar.weekly_briefings set status='PUBLISHED',published_at='2026-09-22T09:00:00+09:00',item_count=1,new_count=1 where id=$1",[old]);
 previousRows=await rows('select to_jsonb(b) row from startup_radar.weekly_briefings b');
 previousRows.push(...await rows('select to_jsonb(i) row from startup_radar.weekly_briefing_items i'));
 previousRpc=await metadata('public.gfc_radar_weekly_briefing(uuid)');
 previousCorrectionAcl=await metadata('startup_radar.apply_publication_correction(uuid,text,text,jsonb)');
 await db.exec(await readFile(new URL(migration,folder),'utf8'));
});
after(async()=>await db?.close());

test('appendix migration preserves historical publications and RPC/correction privileges',async()=>{
 const current=await rows('select to_jsonb(b) row from startup_radar.weekly_briefings b');
 current.push(...await rows('select to_jsonb(i) row from startup_radar.weekly_briefing_items i'));
 assert.deepEqual(current,previousRows);
 assert.deepEqual(await metadata('public.gfc_radar_weekly_briefing(uuid)'),previousRpc);
 assert.deepEqual(await metadata('startup_radar.apply_publication_correction(uuid,text,text,jsonb)'),previousCorrectionAcl);
});

test('only labelled review opportunities are allowed; out-of-scope and empty notes remain rejected',async()=>{
 const b=await briefing(0);
 await assert.rejects(()=>insert(b,2,'OUT_OF_SCOPE',0),/relevance_status_check/);
 for(const review_note of [undefined,null,'','  ',42,{}]){
  await assert.rejects(()=>insert(b,2,'REVIEW_REQUIRED',0,{...facts(2),review_note}),/review_needs_note/);
 }
 await insert(b,2,'REVIEW_REQUIRED',0);
 assert.equal((await rows('select count(*) n from startup_radar.weekly_briefing_items where briefing_id=$1',[b]))[0].n,1);
});

test('publication enforces final appendix order and member RPC exposes the published note',async()=>{
 const b=await briefing(1);
 await insert(b,3,'REVIEW_REQUIRED',0);await insert(b,4,'GFC_RELEVANT',1);
 await assert.rejects(()=>publish(b),/follow confirmed/);
 await rows('update startup_radar.weekly_briefing_items set display_order=display_order+100 where briefing_id=$1',[b]);
 await rows("update startup_radar.weekly_briefing_items set display_order=case when relevance_status='REVIEW_REQUIRED' then 1 else 0 end where briefing_id=$1",[b]);
 await publish(b);
 const article=await as(1,'authenticated',()=>detail(b));
 assert.equal(article.item_count,2);
 assert.deepEqual(article.items.map(x=>x.relevance_status),['GFC_RELEVANT','REVIEW_REQUIRED']);
 assert.equal(article.items[1].facts.review_note,facts(3,true).review_note);
 assert.equal(article.items[1].facts.title,facts(3).title);
 assert.ok(!JSON.stringify(article).includes('classification_method'));
});

test('review-only articles require seven days and a known deadline, just like confirmed articles',async()=>{
 await rows("update startup_radar.runtime_settings set value=jsonb_set(value,'{enabled}','true') where key='notice_policy'");
 const b=await briefing(2);
 await insert(b,5,'REVIEW_REQUIRED',0,facts(5,true,'2026-11-02T09:00:00+09:00'));
 await assert.rejects(()=>publish(b),/seven days/);
 await rows('update startup_radar.weekly_briefing_items set snapshot=$1 where briefing_id=$2',[facts(5,true,'2026-11-03T09:00:00+09:00'),b]);
 await publish(b);
 assert.equal((await as(1,'authenticated',()=>detail(b))).items[0].relevance_status,'REVIEW_REQUIRED');
 const unknown=await briefing(3);await insert(unknown,6,'REVIEW_REQUIRED',0,facts(6,true,null));
 await assert.rejects(()=>publish(unknown),/seven days/);
});

test('explicit correction preserves a retained review note, audits prior items, and cannot add unseen programs',async()=>{
 const b=id(801);const original=(await rows('select published_at,revision from startup_radar.weekly_briefings where id=$1',[b]))[0];
 const keep=[{program_id:id(1003),display_order:0,relevance_status:'REVIEW_REQUIRED',restriction_summary:null,relevance_version:'gfc-v1.2'}];
 const result=(await rows('select startup_radar.apply_publication_correction($1,$2,$3,$4) value',[b,'Explicit test correction preserves the review appendix','추가 확인 1건',keep]))[0].value;
 assert.equal(result.retained,1);assert.equal(result.withdrawn,1);
 assert.equal(Date.parse(result.published_at),new Date(original.published_at).getTime());
 const article=await as(1,'authenticated',()=>detail(b));
 assert.equal(article.items[0].facts.review_note,facts(3,true).review_note);
 const audit=(await rows("select detail from startup_radar.admin_audit where action='WEEKLY_PUBLICATION_CORRECTION' and entity_id=$1",[b]))[0].detail;
 assert.equal(audit.previous_items.length,2);assert.equal(audit.telegram_sent,false);
 assert.equal((await rows('select count(*) n from startup_radar.weekly_announcements'))[0].n,0);
 const invalid=[{...keep[0],program_id:id(1007)}];
 await assert.rejects(()=>rows('select startup_radar.apply_publication_correction($1,$2,$3,$4)',[b,'Explicit invalid addition must roll back','unchanged',invalid]),/only retain/);
 assert.equal((await as(1,'authenticated',()=>detail(b))).items.length,1);
});

test('publication visibility and no-client-write boundaries are unchanged for review appendices',async()=>{
 const b=id(801);
 await assert.rejects(()=>as(null,'anon',()=>detail(b)),/membership/);
 await assert.rejects(()=>as(2,'authenticated',()=>detail(b)),/membership/);
 await assert.rejects(()=>as(1,'authenticated',()=>rows('select evidence from startup_radar.program_relevance')),/permission/);
 await assert.rejects(()=>as(1,'authenticated',()=>rows("update startup_radar.weekly_briefing_items set snapshot='{}' where briefing_id=$1",[b])),/permission/);
 await assert.rejects(()=>as(1,'authenticated',()=>rows('select startup_radar.apply_publication_correction($1,$2,$3,$4)',[b,'Unauthorized correction','none',[]])),/permission/);
 await rows("update startup_radar.runtime_settings set value=jsonb_set(value,'{mode}','\"PRIVATE\"') where key='radar_visibility'");
 await assert.rejects(()=>as(1,'authenticated',()=>detail(b)),/private/);
 assert.equal((await as(99,'authenticated',()=>detail(b))).id,b);
 await rows("update startup_radar.runtime_settings set value=jsonb_set(value,'{mode}','\"MEMBERS_ONLY\"') where key='radar_visibility'");
});
