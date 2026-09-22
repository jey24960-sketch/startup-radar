// Synthetic historical rows only. No service credentials, HTTP or live data.
import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { PGlite } from '@electric-sql/pglite';
import { readFile, readdir } from 'node:fs/promises';

let db, beforeRows, beforeItems, beforeDeliveries;
const migrationName = '20260922131611_weekly_publication_date_titles.sql';
const id = n => `00000000-0000-0000-0000-${String(n).padStart(12,'0')}`;
const rows = async (sql,args=[]) => (await db.query(sql,args)).rows;
const snapshot = async table => (await rows(`select to_jsonb(t) row from startup_radar.${table} t order by 1`)).map(r=>r.row);

before(async () => {
  db=await PGlite.create();
  await db.exec(`create schema auth; create role anon; create role authenticated; create role service_role bypassrls;
    create table auth.users(id uuid primary key);
    create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
    grant usage on schema auth to authenticated; grant execute on function auth.uid() to authenticated;`);
  await db.exec(await readFile(new URL('./fixtures/gfc_identity.sql',import.meta.url),'utf8'));
  const folder=new URL('../supabase/migrations/',import.meta.url);
  for(const file of (await readdir(folder)).filter(f=>f.endsWith('.sql') && f<migrationName).sort()) {
    await db.exec(await readFile(new URL(file,folder),'utf8'));
  }
  await db.query(`insert into startup_radar.ingestion_runs(id,status,trigger_type,finished_at) values($1,'SUCCESS','synthetic-title-test',now())`,[id(1)]);
  const issues=[
    [id(2),'2026-09-14','09.08 ~ 09.14 주간 지원사업 공지','2026-09-15T08:35:11Z','WEEKLY',null,'2026-09-08','2026-09-14'],
    [id(3),'2026-09-14','최초 지원사업 기준 목록','2026-09-15T08:35:11Z','INITIAL_BASELINE','2026-09-15',null,null],
    [id(4),'2026-09-21','09.21 ~ 09.27 주간 지원사업 공지','2026-09-22T11:31:02Z','WEEKLY',null,null,null],
  ];
  for(const [uuid,week,title,published,kind,snapshotDay,displayStart,displayEnd] of issues){
    await db.query(`insert into startup_radar.weekly_briefings(id,week_start,week_end,title,status,published_at,
      summary,collection_status,ingestion_run_id,publication_kind,snapshot_date,display_start,display_end,revision)
      values($1,$2,$2::date+6,$3,'PUBLISHED',$4,'Original summary','SUCCESS',$5,$6,$7,$8,$9,3)`,
      [uuid,week,title,published,id(1),kind,snapshotDay,displayStart,displayEnd]);
  }
  await db.query(`update startup_radar.weekly_briefings set withdrawn_at='2026-09-16T00:00Z',withdrawal_reason='Synthetic withdrawal' where id=$1`,[id(2)]);
  await db.query(`insert into startup_radar.weekly_briefings(id,week_start,week_end,title,status,summary,collection_status,ingestion_run_id)
    values($1,'2026-09-28','2026-10-04','Unpublished editorial draft','DRAFT','Draft','SUCCESS',$2)`,[id(5),id(1)]);
  await db.query(`insert into startup_radar.programs(id,canonical_key,title,organization,status,deadline_type,official_url)
    values($1,'synthetic-title-fixture','Synthetic source facts','Fixture','OPEN','ROLLING','https://example.org/title-test')`,[id(6)]);
  await db.query(`insert into startup_radar.program_versions(id,program_id,version,content_hash,normalized) values($1,$2,1,'fixture','{}')`,[id(7),id(6)]);
  await db.query(`insert into startup_radar.weekly_briefing_items(briefing_id,program_id,program_version_id,change_type,display_order,snapshot,material_hash)
    values($1,$2,$3,'NEW',0,'{"title":"Original immutable source snapshot"}','material')`,[id(4),id(6),id(7)]);
  await db.query(`update startup_radar.weekly_briefings set item_count=1,new_count=1 where id=$1`,[id(4)]);
  await db.query(`insert into startup_radar.weekly_announcements(briefing_id,chat_id,payload,state,target_kind,receipt,delivered_at)
    values($1,'synthetic-channel','Original delivered date-range payload','DELIVERED','OFFICIAL_CHANNEL','{"message_id":123}','2026-09-22T11:32:34Z')`,[id(4)]);
  await db.query(`insert into startup_radar.weekly_announcements(briefing_id,chat_id,payload,state,target_kind)
    values($1,'synthetic-channel','Original failed payload','FAILED','OFFICIAL_CHANNEL')`,[id(2)]);
  beforeRows=await snapshot('weekly_briefings');
  beforeItems=await snapshot('weekly_briefing_items');
  beforeDeliveries=await snapshot('weekly_announcements');
  await db.exec(await readFile(new URL(migrationName,folder),'utf8'));
});
after(async()=>{if(db)await db.close();});

test('historical weekly and baseline titles change; every other stored field and delivery remains identical',async()=>{
  const afterRows=await snapshot('weekly_briefings');
  const expected={ [id(2)]:'9월 15일자 주간 지원사업 공지', [id(3)]:'9월 15일자 최초 지원사업 목록',
    [id(4)]:'9월 22일자 주간 지원사업 공지', [id(5)]:'Unpublished editorial draft' };
  for(const row of afterRows){
    assert.equal(row.title,expected[row.id]);
    const original=beforeRows.find(b=>b.id===row.id);
    assert.deepEqual({...row,title:original.title},original);
  }
  assert.deepEqual(await snapshot('weekly_briefing_items'),beforeItems);
  assert.deepEqual(await snapshot('weekly_announcements'),beforeDeliveries);
  const audit=await rows(`select entity_id,detail from startup_radar.admin_audit where action='WEEKLY_PUBLICATION_TITLE_NORMALIZED'`);
  assert.equal(audit.length,3);
  for(const row of audit){
    assert.equal(row.detail.before_title,beforeRows.find(b=>b.id===row.entity_id).title);
    assert.equal(row.detail.after_title,expected[row.entity_id]);
  }
});

test('repeating the corrective update makes no changes and creates no duplicate audit',async()=>{
  const before=await snapshot('weekly_briefings');
  await db.exec(`update startup_radar.weekly_briefings set title=startup_radar.publication_date_title(publication_kind,published_at)
    where published_at is not null and title is distinct from startup_radar.publication_date_title(publication_kind,published_at)`);
  assert.deepEqual(await snapshot('weekly_briefings'),before);
  assert.equal((await rows(`select count(*)::int n from startup_radar.admin_audit where action='WEEKLY_PUBLICATION_TITLE_NORMALIZED'`))[0].n,3);
});

test('SQL uses Seoul midnight and never guesses missing dates',async()=>{
  const result=(await rows(`select startup_radar.publication_date_title('WEEKLY','2026-09-21T14:59:59Z') before_midnight,
    startup_radar.publication_date_title('WEEKLY','2026-09-21T15:00:00Z') at_midnight,
    startup_radar.publication_date_title('INITIAL_BASELINE','2026-12-31T15:00:00Z') new_year,
    startup_radar.publication_date_title('WEEKLY',null) missing`))[0];
  assert.deepEqual(result,{before_midnight:'9월 21일자 주간 지원사업 공지',at_midnight:'9월 22일자 주간 지원사업 공지',new_year:'1월 1일자 최초 지원사업 목록',missing:null});
});

test('old worker cannot reintroduce a period title; future first publication and revision use persisted dates',async()=>{
  await db.exec('begin; set local role service_role');
  try{
    await db.query(`update startup_radar.weekly_briefings set title='old worker period label' where id=$1`,[id(4)]);
    assert.equal((await rows('select title from startup_radar.weekly_briefings where id=$1',[id(4)]))[0].title,'9월 22일자 주간 지원사업 공지');
    await db.query(`update startup_radar.weekly_briefings set title='Old draft range',status='PUBLISHED',published_at='2026-09-28T15:00Z' where id=$1`,[id(5)]);
    await db.query(`update startup_radar.weekly_briefings set title='Revision date should not replace first day',revision=revision+1 where id=$1`,[id(5)]);
    assert.equal((await rows('select title from startup_radar.weekly_briefings where id=$1',[id(5)]))[0].title,'9월 29일자 주간 지원사업 공지');
    assert.equal((await rows(`select count(*)::int n from startup_radar.admin_audit where action='WEEKLY_PUBLICATION_TITLE_NORMALIZED'`))[0].n,3);
  }finally{await db.exec('rollback; reset role');}
});

test('member and anonymous roles acquire no title write or helper privileges',async()=>{
  for(const role of ['anon','authenticated']){
    const row=(await rows(`select has_function_privilege($1,'startup_radar.publication_date_title(text,timestamptz)','EXECUTE') helper,
      has_function_privilege($1,'startup_radar.normalize_publication_date_title()','EXECUTE') trigger,
      has_table_privilege($1,'startup_radar.weekly_briefings','UPDATE') writable`,[role]))[0];
    assert.deepEqual(row,{helper:false,trigger:false,writable:false});
  }
});
