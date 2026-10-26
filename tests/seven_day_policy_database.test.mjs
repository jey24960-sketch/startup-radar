import test from 'node:test';
import assert from 'node:assert/strict';
import {PGlite} from '@electric-sql/pglite';
import {readFile,readdir} from 'node:fs/promises';

test('weekly DB publication guard enforces seven days without rewriting historical snapshots',async()=>{
 const db=await PGlite.create();
 try {
  await db.exec(`create schema auth;create role anon;create role authenticated;create role service_role bypassrls;
  create table auth.users(id uuid primary key);
  create function auth.uid() returns uuid language sql stable as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
  grant usage on schema auth to authenticated;grant execute on function auth.uid() to authenticated;`);
  await db.exec(await readFile('tests/fixtures/gfc_identity.sql','utf8'));
  for(const file of (await readdir('supabase/migrations')).filter(f=>f.endsWith('.sql')).sort())await db.exec(await readFile('supabase/migrations/'+file,'utf8'));
  const query=async(sql,args=[]) => (await db.query(sql,args)).rows;
  const run=(await query("insert into startup_radar.ingestion_runs(status,trigger_type) values('SUCCESS','test') returning id"))[0].id;
  const p=(await query("insert into startup_radar.programs(canonical_key,title,organization,status,deadline_type,official_url) values('guard','guard','test','OPEN','FIXED_DATE','https://example.org') returning id"))[0].id;
  const v=(await query("insert into startup_radar.program_versions(program_id,version,content_hash,normalized) values($1,1,'hash','{}') returning id",[p]))[0].id;
  const b=(await query("insert into startup_radar.weekly_briefings(week_start,week_end,title,summary,status,collection_status,ingestion_run_id) values('2026-10-26','2026-11-01','test','test','DRAFT','SUCCESS',$1) returning id",[run]))[0].id;
  const short={title:'short',application_end_at:'2026-10-30T23:59:59+09:00'};
  await query("insert into startup_radar.weekly_briefing_items(briefing_id,program_id,program_version_id,change_type,display_order,snapshot,material_hash,relevance_status) values($1,$2,$3,'NEW',0,$4,'m','GFC_RELEVANT')",[b,p,v,short]);
  await db.exec("update startup_radar.runtime_settings set value=jsonb_set(value,'{enabled}','true') where key='notice_policy'");
  await assert.rejects(()=>query("update startup_radar.weekly_briefings set status='PUBLISHED',published_at='2026-10-26T09:00:00+09:00' where id=$1",[b]),/seven days/);
  const valid={title:'valid',application_end_at:'2026-11-02T09:00:00+09:00'};
  await query('update startup_radar.weekly_briefing_items set snapshot=$1 where briefing_id=$2',[valid,b]);
  await query("update startup_radar.weekly_briefings set status='PUBLISHED',published_at='2026-10-26T09:00:00+09:00' where id=$1",[b]);
  const actual=(await query('select snapshot from startup_radar.weekly_briefing_items where briefing_id=$1',[b]))[0].snapshot;
  assert.deepEqual(actual,valid);
  await assert.rejects(()=>query('update startup_radar.weekly_briefing_items set snapshot=$1 where briefing_id=$2',[short,b]),/seven days/);
  await db.exec('set role authenticated');
  await assert.rejects(()=>query('select * from startup_radar.discovery_slots'),/permission/);
  await db.exec('reset role');
 } finally {await db.close();}
});
