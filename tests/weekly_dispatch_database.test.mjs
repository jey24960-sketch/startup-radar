// Isolated SQL contract tests. net/cron/Vault below are synthetic transports;
// these tests never make HTTP requests or claim hosted Supabase integration.
import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { PGlite } from '@electric-sql/pglite';
import { readFile, readdir } from 'node:fs/promises';

let db;
const WEEK = '2026-09-21';
const at = minute => `2026-09-22T00:${String(minute).padStart(2, '0')}:00Z`;
const id = n => `00000000-0000-0000-0000-${String(n).padStart(12, '0')}`;
const rows = async (sql, args = []) => (await db.query(sql, args)).rows;
const value = async (sql, args = []) => (await rows(sql, args))[0]?.v;
const tick = date => value('select startup_radar.weekly_scheduler_tick_at($1) v', [date]);
const plan = date => value('select startup_radar.weekly_schedule_plan($1) v', [date]);
const count = table => value(`select count(*)::int v from ${table}`);
async function enable() {
  await rows(`update startup_radar.runtime_settings set value=value||jsonb_build_object('enabled',true,'active_from_week',$1::text) where key='weekly_scheduler'`, [WEEK]);
}
async function rejected(sql, args = [], pattern = /permission denied/) {
  await db.exec('savepoint rejection');
  let error;
  try { await rows(sql, args); } catch (caught) { error = caught; }
  await db.exec('rollback to savepoint rejection; release savepoint rejection');
  assert.ok(error, 'SQL must reject');
  assert.match(error.message, pattern);
}
async function scenario(fn) {
  await db.exec('begin');
  try { await fn(); } finally { await db.exec('rollback; reset role'); }
}
async function transport() {
  await db.exec(`
    create schema net; create schema vault; create schema cron;
    create table cron.job(jobname text, schedule text, command text, active boolean,
      database text default current_database(), username text default current_user);
    create table vault.decrypted_secrets(name text, decrypted_secret text);
    insert into vault.decrypted_secrets values('startup_radar_github_dispatch','synthetic-test-token');
    create table net.test_calls(id bigserial primary key, url text, body jsonb,
      expected_headers boolean, timeout_milliseconds integer);
    create table net._http_response(id bigint primary key,status_code integer,
      timed_out boolean default false,error_msg text,created timestamptz default now());
    create function net.http_post(url text,body jsonb default '{}'::jsonb,params jsonb default '{}'::jsonb,
      headers jsonb default '{}'::jsonb,timeout_milliseconds integer default 1000) returns bigint
      language plpgsql as $$ declare result bigint; begin
        insert into net.test_calls(url,body,expected_headers,timeout_milliseconds)
        values(url,body,headers->>'Authorization'='Bearer synthetic-test-token'
          and headers->>'X-GitHub-Api-Version'='2022-11-28',timeout_milliseconds) returning id into result;
        return result;
      end $$;
  `);
}
before(async () => {
  db = await PGlite.create();
  await db.exec(`create schema auth; create role anon; create role authenticated; create role service_role bypassrls;
    create table auth.users(id uuid primary key);
    create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
    grant usage on schema auth to authenticated; grant execute on function auth.uid() to authenticated;`);
  await db.exec(await readFile(new URL('./fixtures/gfc_identity.sql', import.meta.url), 'utf8'));
  const folder = new URL('../supabase/migrations/', import.meta.url);
  for (const file of (await readdir(folder)).filter(file => file.endsWith('.sql')).sort()) await db.exec(await readFile(new URL(file, folder), 'utf8'));
  await db.exec(`insert into auth.users values('${id(1)}'),('${id(99)}');
    insert into public.test_gfc_roles values('${id(99)}','admin');`);
});
after(async () => { await db?.close(); });

test('migration defaults remain inert, require explicit future activation and a registered local cron job', () => scenario(async () => {
  assert.equal((await plan(at(0))).state, 'DISABLED');
  assert.equal((await tick(at(0))).state, 'DISABLED');
  assert.equal(await count('startup_radar.weekly_schedule_requests'), 0);
  await rejected("select startup_radar.configure_weekly_scheduler(true,date_trunc('week',now())::date+7,'synthetic activation')", [], /Register/);
  await transport();
  await db.exec("insert into cron.job(jobname,schedule,command,active) values('startup-radar-weekly-dispatch','*/5 * * * *','select startup_radar.weekly_scheduler_tick();',true)");
  await rejected("select startup_radar.configure_weekly_scheduler(true,date_trunc('week',now())::date-7,'synthetic activation')", [], /future due/);
  const configured = await value("select startup_radar.configure_weekly_scheduler(true,date_trunc('week',now())::date+7,'synthetic activation') v");
  assert.equal(configured.enabled, true);
  assert.equal(await count('startup_radar.admin_audit'), 1);
  assert.equal(await count('net.test_calls'), 0, 'configuration itself never dispatches');
}));

test('a cron job targeting another database is not registration for this database', () => scenario(async () => {
  await transport();
  await db.exec("insert into cron.job(jobname,schedule,command,active,database) values('startup-radar-weekly-dispatch','*/5 * * * *','select startup_radar.weekly_scheduler_tick();',true,'different-database')");
  assert.equal(await value('select startup_radar.weekly_cron_registered() v'), false);
}));

test('dispatch fixes destination/ref and uses one durable request; HTTP acceptance is not execution or publication', () => scenario(async () => {
  await transport(); await enable();
  assert.equal((await tick(at(0))).state, 'DISPATCH_PENDING');
  const calls = await rows('select * from net.test_calls');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, 'https://api.github.com/repos/jey24960-sketch/startup-radar/actions/workflows/startup_radar_v2.yml/dispatches');
  assert.equal(calls[0].body.ref, 'main');
  assert.equal(calls[0].body.inputs.kind, 'WEEKLY');
  assert.equal(calls[0].body.inputs.expected_week_start, WEEK);
  assert.equal(calls[0].expected_headers, true);
  assert.equal(calls[0].timeout_milliseconds, 10000);
  await rows('insert into net._http_response(id,status_code) values($1,204)', [calls[0].id]);
  assert.equal((await tick(at(5))).state, 'DISPATCH_PENDING');
  const observed = await plan(at(5));
  assert.equal(observed.latest_attempt.response_state, 'ACCEPTED');
  assert.equal(observed.request.execution_id, null);
  assert.equal(await count('startup_radar.worker_executions'), 0);
  assert.equal(await count('startup_radar.weekly_briefings'), 0);
  assert.equal(await count('startup_radar.weekly_announcements'), 0);
}));

test('missing acknowledgements retry the same identity after grace and stop at three attempts', () => scenario(async () => {
  await transport(); await enable();
  for (const minute of [0, 10, 20]) assert.equal((await tick(at(minute))).state, 'DISPATCH_PENDING');
  assert.equal((await tick(at(30))).state, 'RETRY_EXHAUSTED');
  assert.equal((await tick(at(50))).state, 'RETRY_EXHAUSTED');
  const calls = await rows('select body from net.test_calls order by id');
  assert.equal(calls.length, 3);
  assert.ok(calls.every(call => call.body.inputs.scheduler_request_id === calls[0].body.inputs.scheduler_request_id));
  assert.equal(await count('startup_radar.weekly_schedule_requests'), 1);
  assert.deepEqual((await rows('select response_state from startup_radar.weekly_dispatch_attempts order by attempt_number')).map(row => row.response_state), ['UNKNOWN', 'UNKNOWN', 'UNKNOWN']);
}));

test('accepted dispatches without a worker also retry with the same identity, while responses omit provider details', () => scenario(async () => {
  await transport(); await enable();
  await tick(at(0));
  await db.exec('insert into net._http_response(id,status_code) select id,204 from net.test_calls');
  assert.equal((await tick(at(10))).state, 'DISPATCH_PENDING');
  const calls = await rows('select body from net.test_calls order by id');
  assert.equal(calls.length, 2);
  assert.equal(calls[0].body.inputs.scheduler_request_id, calls[1].body.inputs.scheduler_request_id);
  const latest = (await rows('select id from net.test_calls order by id desc limit 1'))[0];
  await rows('insert into net._http_response(id,timed_out,error_msg) values($1,true,$2)', [latest.id, 'synthetic provider detail must stay private']);
  await tick(at(15));
  const observed = await plan(at(15));
  assert.equal(observed.latest_attempt.response_state, 'UNKNOWN');
  assert.ok(!JSON.stringify(observed).includes('synthetic provider detail'));
  assert.ok(!JSON.stringify(observed).includes('synthetic-test-token'));
}));

test('explicit rejection stops retry while rate limits and server failures remain bounded retryable responses', () => scenario(async () => {
  await transport(); await enable();
  await tick(at(0));
  const call = (await rows('select id from net.test_calls'))[0];
  await rows('insert into net._http_response(id,status_code) values($1,403)', [call.id]);
  assert.equal((await tick(at(5))).state, 'DISPATCH_REJECTED');
  assert.equal((await tick(at(40))).state, 'DISPATCH_REJECTED');
  assert.equal(await count('net.test_calls'), 1);
  await rows('update net._http_response set status_code=429 where id=$1', [call.id]);
  await db.exec("update startup_radar.weekly_dispatch_attempts set response_state='PENDING'");
  assert.equal((await tick(at(10))).state, 'DISPATCH_PENDING');
  assert.equal((await rows('select response_state from startup_radar.weekly_dispatch_attempts where attempt_number=1'))[0].response_state, 'RETRYABLE');
  const second = (await rows('select id from net.test_calls order by id desc limit 1'))[0];
  await rows('insert into net._http_response(id,status_code) values($1,503)', [second.id]);
  await tick(at(20));
  assert.equal((await rows('select response_state from startup_radar.weekly_dispatch_attempts where attempt_number=2'))[0].response_state, 'RETRYABLE');
}));

test('pause records a skipped week and resume cannot automatically catch it up', () => scenario(async () => {
  await transport(); await enable();
  await db.exec("update startup_radar.runtime_settings set value=value||'{\"enabled\":false}'::jsonb where key='radar_operation'");
  assert.equal((await tick(at(0))).state, 'PAUSED');
  await db.exec("update startup_radar.runtime_settings set value=value||'{\"enabled\":true}'::jsonb where key='radar_operation'");
  assert.equal((await tick(at(10))).state, 'SKIPPED_PAUSED');
  assert.equal(await count('net.test_calls'), 0);
  assert.equal((await rows('select suppressed_reason from startup_radar.weekly_schedule_requests'))[0].suppressed_reason, 'OPERATOR_PAUSED');
}));

test('existing owners and terminal failures never age out into a new execution attempt', () => scenario(async () => {
  await transport(); await enable();
  await rows("insert into startup_radar.worker_executions(id,kind,state,owner,started_at) values($1,'WEEKLY','RUNNING','{}',$2)", [id(10), at(0)]);
  assert.equal((await tick(at(5))).state, 'RUNNING');
  assert.equal((await tick('2026-09-22T08:00:00Z')).state, 'LONG_RUNNING');
  await rows("update startup_radar.worker_executions set state='FAILED',finished_at=$1 where id=$2", [at(5), id(10)]);
  assert.equal((await tick(at(10))).state, 'FAILED');
  await db.exec("update startup_radar.worker_executions set state='ABANDONED'");
  assert.equal((await tick(at(20))).state, 'UNCERTAIN');
  assert.equal(await count('net.test_calls'), 0);
}));

test('an older unfinished owner blocks current-week dispatch and an existing publication is never republished', () => scenario(async () => {
  await transport(); await enable();
  await rows("insert into startup_radar.worker_executions(id,kind,state,owner,started_at) values($1,'INGEST','RUNNING','{}','2026-09-14T00:00:00Z')", [id(20)]);
  assert.equal((await tick(at(0))).state, 'BLOCKED_RUNNING');
  await rows("update startup_radar.worker_executions set kind='WEEKLY' where id=$1", [id(20)]);
  assert.equal((await plan(at(0))).state, 'BLOCKED_RUNNING', 'a prior-week owner must not look like this week is executing');
  assert.equal((await tick(at(5))).state, 'BLOCKED_RUNNING');
  await rows("update startup_radar.worker_executions set finished_at=$1,state='SUCCESS' where id=$2", [at(1), id(20)]);
  await rows("insert into startup_radar.ingestion_runs(id,status,trigger_type) values($1,'SUCCESS','weekly')", [id(21)]);
  await rows("insert into startup_radar.weekly_briefings(week_start,week_end,title,status,published_at,summary,collection_status,ingestion_run_id) values($1,$1::date+6,'Synthetic existing week','PUBLISHED',$2,'Test','SUCCESS',$3)", [WEEK, at(2), id(21)]);
  assert.equal((await tick(at(5))).state, 'PUBLISHED');
  assert.equal(await count('net.test_calls'), 0);
  assert.equal(await count('startup_radar.weekly_schedule_requests'), 0);
}));

test('Seoul Monday and Tuesday boundaries never dispatch previous or premature weeks', () => scenario(async () => {
  await transport(); await enable();
  assert.equal((await tick('2026-09-20T14:59:59Z')).state, 'NOT_DUE');
  assert.equal((await tick('2026-09-20T15:00:00Z')).state, 'NOT_DUE');
  assert.equal((await tick('2026-09-21T23:59:59Z')).state, 'NOT_DUE');
  assert.equal(await count('net.test_calls'), 0);
  await tick(at(0));
  const request = (await rows('select week_start::text,scheduled_at from startup_radar.weekly_schedule_requests'))[0];
  assert.equal(request.week_start, WEEK);
  assert.equal(new Date(request.scheduled_at).toISOString(), '2026-09-22T00:00:00.000Z');
  await rejected("update startup_radar.weekly_schedule_requests set scheduled_at='2026-09-22T06:00:00Z'", [], /check constraint/);
  assert.equal((await tick('2026-09-27T15:00:00Z')).state, 'NOT_DUE');
  assert.equal(await count('net.test_calls'), 1);
}));

test('anonymous, missing-profile, member and admin browser roles cannot dispatch/configure or bypass the base RPC', () => scenario(async () => {
  for (const [role, user] of [['anon', null], ['authenticated', id(404)], ['authenticated', id(1)], ['authenticated', id(99)]]) {
    await rows("select set_config('request.jwt.claim.sub',$1,false)", [user || '']);
    await db.exec(`set role ${role}`);
    await rejected('select startup_radar.weekly_scheduler_tick()');
    await rejected('select startup_radar.weekly_scheduler_tick_at(now())');
    await rejected("select startup_radar.configure_weekly_scheduler(false,null,'attempted browser switch')");
    await rejected('select * from startup_radar.weekly_schedule_requests');
    await rejected('select public.gfc_radar_admin_weekly_status_base()');
    if (user !== id(99)) await rejected('select public.gfc_radar_admin_weekly_status()', [], /permission denied|GFC admin/);
    await db.exec('reset role');
  }
}));

test('public admin RPC preserves observed facts, changes only the timetable to 09:00 KST and adds safe runtime observations', () => scenario(async () => {
  await rows("select set_config('request.jwt.claim.sub',$1,false)", [id(99)]);
  const original = await value('select public.gfc_radar_admin_weekly_status_base() v');
  await db.exec('set role authenticated');
  const current = await value('select public.gfc_radar_admin_weekly_status() v');
  await db.exec('reset role');
  assert.equal(current.schedule.runtime.enabled, false);
  assert.equal(current.schedule.runtime.registered, false);
  assert.equal(current.schedule.execution_gate, 'UNKNOWN');
  assert.equal(current.schedule.delivery_gate, 'UNKNOWN');
  const expectedDue = new Date(new Date(original.scheduled_at).getTime() - 6 * 3600000);
  assert.equal(new Date(current.scheduled_at).toISOString(), expectedDue.toISOString());
  const expectedNext = new Date(expectedDue.getTime() + (new Date(current.as_of) < expectedDue ? 0 : 7 * 86400000));
  assert.equal(new Date(current.next_scheduled_at).toISOString(), expectedNext.toISOString());
  delete current.schedule.runtime;
  assert.deepEqual(current, {...original,scheduled_at:current.scheduled_at,next_scheduled_at:current.next_scheduled_at});
}));

test('the augmented admin observation executes inside a read-only transaction', () => scenario(async () => {
  await db.exec('set transaction read only');
  await rows("select set_config('request.jwt.claim.sub',$1,false)", [id(99)]);
  await db.exec('set role authenticated');
  const current = await value('select public.gfc_radar_admin_weekly_status() v');
  assert.equal(current.schedule.runtime.state, 'DISABLED');
  await db.exec('reset role');
  assert.equal(await count('startup_radar.admin_audit'), 0);
  assert.equal(await count('startup_radar.weekly_schedule_requests'), 0);
}));

test('missing provider configuration has an explicit state and produces no successful attempt', () => scenario(async () => {
  await enable();
  assert.equal((await tick(at(0))).state, 'CONFIGURATION_ERROR');
  assert.equal(await count('startup_radar.weekly_dispatch_attempts'), 0);
  const observed = await plan(at(5));
  assert.equal(observed.last_tick_state, 'CONFIGURATION_ERROR');
  assert.equal(observed.enabled, true);
}));
