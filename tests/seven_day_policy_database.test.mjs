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
  // Model a pre-policy historical row. The cleanup exception must not bless
  // an item which never satisfied the preparation promise at first publication.
  const invalidClock=(await query("select now()-interval '14 days' published_at,now()-interval '10 days' deadline"))[0];
  const invalidHistorical=(await query("insert into startup_radar.weekly_briefings(week_start,week_end,title,summary,status,published_at,collection_status,ingestion_run_id) values('2026-09-28','2026-10-04','historical invalid','historical invalid','PUBLISHED',$1,'SUCCESS',$2) returning id",[invalidClock.published_at,run]))[0].id;
  const invalidLegacy={title:'historical invalid',application_end_at:invalidClock.deadline.toISOString(),support_summary:'요약\n공식 공고 상세\n원문'};
  await query("insert into startup_radar.weekly_briefing_items(briefing_id,program_id,program_version_id,change_type,display_order,snapshot,material_hash,relevance_status) values($1,$2,$3,'NEW',0,$4,'invalid','GFC_RELEVANT')",[invalidHistorical,p,v,invalidLegacy]);
  await db.exec("update startup_radar.runtime_settings set value=jsonb_set(value,'{enabled}','true') where key='notice_policy'");
  await assert.rejects(()=>query('update startup_radar.weekly_briefing_items set snapshot=$1 where briefing_id=$2',[{...invalidLegacy,support_summary:'요약'},invalidHistorical]),/seven days/);
  await assert.rejects(()=>query("update startup_radar.weekly_briefings set status='PUBLISHED',published_at='2026-10-26T09:00:00+09:00' where id=$1",[b]),/seven days/);
  const valid={title:'valid',application_end_at:'2026-11-02T09:00:00+09:00'};
  await query('update startup_radar.weekly_briefing_items set snapshot=$1 where briefing_id=$2',[valid,b]);
  await query("update startup_radar.weekly_briefings set status='PUBLISHED',published_at='2026-10-26T09:00:00+09:00' where id=$1",[b]);
  const actual=(await query('select snapshot from startup_radar.weekly_briefing_items where briefing_id=$1',[b]))[0].snapshot;
  assert.deepEqual(actual,valid);
  await assert.rejects(()=>query('update startup_radar.weekly_briefing_items set snapshot=$1 where briefing_id=$2',[short,b]),/seven days/);
  // A published item's deadline can now be past even though it originally
  // afforded seven days. Only removal of the known page-dump presentation may
  // use that original publication clock; ordinary revisions keep today's gate.
  const clock=(await query("select now()-interval '14 days' published_at,now()-interval '1 day' deadline"))[0];
  const archived=(await query("insert into startup_radar.weekly_briefings(week_start,week_end,title,summary,status,collection_status,ingestion_run_id) values('2026-10-12','2026-10-18','legacy','legacy','DRAFT','SUCCESS',$1) returning id",[run]))[0].id;
  const legacy={title:'legacy',application_end_at:clock.deadline.toISOString(),support_summary:'공식 요약\n공식 공고 상세\n반복 제목\n지원내용\n무료 멘토링',applicant_summary:'예비창업팀'};
  const clean={...legacy,support_summary:'공식 요약\n무료 멘토링',applicant_summary:'예비창업팀\n제외대상\n없음'};
  await query("insert into startup_radar.weekly_briefing_items(briefing_id,program_id,program_version_id,change_type,display_order,snapshot,material_hash,relevance_status) values($1,$2,$3,'NEW',0,$4,'legacy','GFC_RELEVANT')",[archived,p,v,legacy]);
  await query("update startup_radar.weekly_briefings set status='PUBLISHED',published_at=$1 where id=$2",[clock.published_at,archived]);
  const v2=(await query("insert into startup_radar.program_versions(program_id,version,content_hash,normalized) values($1,2,'hash2','{}') returning id",[p]))[0].id;
  // A genuine date/title/version change cannot be smuggled into the cleanup.
  await assert.rejects(()=>query('update startup_radar.weekly_briefing_items set snapshot=$1 where briefing_id=$2',[{...clean,application_end_at:new Date(clock.deadline.getTime()+86400000).toISOString()},archived]),/seven days/);
  await assert.rejects(()=>query('update startup_radar.weekly_briefing_items set snapshot=$1 where briefing_id=$2',[{...clean,title:'new title'},archived]),/seven days/);
  await assert.rejects(()=>query('update startup_radar.weekly_briefing_items set snapshot=$1,program_version_id=$2 where briefing_id=$3',[clean,v2,archived]),/seven days/);
  await assert.rejects(()=>query('update startup_radar.weekly_briefing_items set program_version_id=$1 where briefing_id=$2',[v2,archived]),/seven days/);
  // A marker alone never authorizes arbitrary replacement descriptions.
  await assert.rejects(()=>query('update startup_radar.weekly_briefing_items set snapshot=$1 where briefing_id=$2',[clean,archived]),/seven days/);
  const authorize=()=>query("insert into startup_radar.admin_audit(action,entity_id,detail) values('WEEKLY_SOURCE_TEXT_REPAIR_AUTHORIZATION',$1,jsonb_build_object('reason','Verified legacy source-text correction','transaction_id',txid_current(),'actor','PRIVILEGED_PUBLICATION_OPERATOR','patches',jsonb_build_array(jsonb_build_object('program_id',$2::text,'program_version_id',$3::text,'before_snapshot',$4::jsonb,'after_snapshot',$5::jsonb))))",[archived,p,v,legacy,clean]);
  await db.exec('begin');
  await authorize();
  await assert.rejects(()=>query('update startup_radar.weekly_briefing_items set snapshot=$1 where briefing_id=$2',[{...clean,support_summary:'새로운 지원금 1억원'},archived]),/seven days/);
  await db.exec('rollback');
  // Authorization from another transaction cannot be replayed.
  await authorize();
  await assert.rejects(()=>query('update startup_radar.weekly_briefing_items set snapshot=$1 where briefing_id=$2',[clean,archived]),/seven days/);
  await db.exec('begin');
  await authorize();
  await query('update startup_radar.weekly_briefing_items set snapshot=$1 where briefing_id=$2',[clean,archived]);
  await db.exec('commit');
  assert.deepEqual((await query('select snapshot from startup_radar.weekly_briefing_items where briefing_id=$1',[archived]))[0].snapshot,clean);
  assert.equal((await query('select published_at from startup_radar.weekly_briefings where id=$1',[archived]))[0].published_at.toISOString(),clock.published_at.toISOString());
  assert.equal((await query("select (value->>'enabled')::boolean enabled from startup_radar.runtime_settings where key='notice_policy'"))[0].enabled,true);
  // Once corrected there is no reusable exception for subsequent content edits.
  await assert.rejects(()=>query('update startup_radar.weekly_briefing_items set snapshot=$1 where briefing_id=$2',[{...clean,support_summary:'새로운 일반 지원내용'},archived]),/seven days/);
  // Reviewed facts need no legacy marker, but must match a privileged exact
  // before/after authorization in this transaction and may not touch dates/IDs.
  const reviewed={...clean,support_summary:'시제품 제작비 최대 500만원',applicant_summary:'청주 7년 미만 기업',organization:'실제 수행기관'};
  const authorizeReviewed=()=>query("insert into startup_radar.admin_audit(action,entity_id,detail) values('WEEKLY_EDITORIAL_REPAIR_AUTHORIZATION',$1,jsonb_build_object('reason','공식 원문에 따른 지원·자격·기관 정정','transaction_id',txid_current(),'actor','PRIVILEGED_PUBLICATION_OPERATOR','patches',jsonb_build_array(jsonb_build_object('program_id',$2::text,'program_version_id',$3::text,'before_snapshot',$4::jsonb,'after_snapshot',$5::jsonb))))",[archived,p,v,clean,reviewed]);
  await authorizeReviewed();
  await assert.rejects(()=>query('update startup_radar.weekly_briefing_items set snapshot=$1 where briefing_id=$2',[reviewed,archived]),/seven days/);
  await db.exec('begin');
  await authorizeReviewed();
  await query('update startup_radar.weekly_briefing_items set snapshot=$1 where briefing_id=$2',[reviewed,archived]);
  await db.exec('commit');
  await db.exec('begin');
  await query("insert into startup_radar.admin_audit(action,entity_id,detail) values('WEEKLY_EDITORIAL_REPAIR_AUTHORIZATION',$1,jsonb_build_object('reason','원문 정정이라도 날짜 변경 우회는 불허','transaction_id',txid_current(),'actor','PRIVILEGED_PUBLICATION_OPERATOR','patches',jsonb_build_array(jsonb_build_object('program_id',$2::text,'program_version_id',$3::text,'before_snapshot',$4::jsonb,'after_snapshot',$5::jsonb))))",[archived,p,v,reviewed,{...reviewed,application_end_at:clock.published_at.toISOString()}]);
  await assert.rejects(()=>query('update startup_radar.weekly_briefing_items set snapshot=$1 where briefing_id=$2',[{...reviewed,application_end_at:clock.published_at.toISOString()},archived]),/seven days/);
  await db.exec('rollback');
  // A marker embedded in a normal sentence is not the legacy page delimiter.
  const draft=(await query("insert into startup_radar.weekly_briefings(week_start,week_end,title,summary,status,collection_status,ingestion_run_id) values('2026-10-05','2026-10-11','inline','inline','DRAFT','SUCCESS',$1) returning id",[run]))[0].id;
  const inline={...legacy,support_summary:'문장 속 공식 공고 상세 문구'};
  await query("insert into startup_radar.weekly_briefing_items(briefing_id,program_id,program_version_id,change_type,display_order,snapshot,material_hash,relevance_status) values($1,$2,$3,'NEW',0,$4,'inline','GFC_RELEVANT')",[draft,p,v,inline]);
  await query("update startup_radar.weekly_briefings set status='PUBLISHED',published_at=$1 where id=$2",[clock.published_at,draft]);
  await assert.rejects(()=>query('update startup_radar.weekly_briefing_items set snapshot=$1 where briefing_id=$2',[clean,draft]),/seven days/);
  await db.exec('set role authenticated');
  await assert.rejects(()=>query('select * from startup_radar.discovery_slots'),/permission/);
  await db.exec('reset role');
 } finally {await db.close();}
});
