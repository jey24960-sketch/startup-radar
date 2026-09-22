begin;
set local lock_timeout='3s';
set local statement_timeout='30s';

-- Additive and inert: no extensions, jobs, secrets or production switches are
-- enabled by this migration. Activation is an explicit later operation.
insert into startup_radar.runtime_settings(key,value)
values('weekly_scheduler','{"enabled":false,"active_from_week":null,"last_tick_at":null,"last_tick_state":"DISABLED","version":1}')
on conflict(key) do nothing;

create table startup_radar.weekly_schedule_requests (
 id uuid primary key default gen_random_uuid(),
 week_start date not null unique check(extract(isodow from week_start)=1),
 scheduled_at timestamptz not null,
 created_at timestamptz not null default now(),
 execution_id uuid unique references startup_radar.worker_executions(id),
 suppressed_reason text check(suppressed_reason in ('OPERATOR_PAUSED')),
 check(scheduled_at=(week_start+interval '1 day 9 hours') at time zone 'Asia/Seoul'),
 check(execution_id is null or suppressed_reason is null)
);
create table startup_radar.weekly_dispatch_attempts (
 id uuid primary key default gen_random_uuid(),
 request_id uuid not null references startup_radar.weekly_schedule_requests(id),
 attempt_number integer not null check(attempt_number between 1 and 3),
 http_request_id bigint unique,
 requested_at timestamptz not null default now(),
 response_state text not null default 'PENDING'
   check(response_state in ('PENDING','ACCEPTED','RETRYABLE','REJECTED','UNKNOWN')),
 responded_at timestamptz,
 http_status integer,
 unique(request_id,attempt_number)
);
alter table startup_radar.weekly_schedule_requests enable row level security;
alter table startup_radar.weekly_dispatch_attempts enable row level security;
revoke all on startup_radar.weekly_schedule_requests,startup_radar.weekly_dispatch_attempts from public,anon,authenticated;
grant select,insert,update on startup_radar.weekly_schedule_requests,startup_radar.weekly_dispatch_attempts to service_role;

create function startup_radar.weekly_cron_registered() returns boolean
language plpgsql stable security definer set search_path='' as $$
declare registered boolean;
begin
 if to_regclass('cron.job') is null then return false; end if;
 execute $q$select exists(select 1 from cron.job where jobname='startup-radar-weekly-dispatch'
   and active and database=current_database() and username=current_user
   and schedule='*/5 * * * *'
   and command='select startup_radar.weekly_scheduler_tick();')$q$ into registered;
 return registered;
end $$;

-- Pure observation at a supplied clock is testable without moving the server
-- clock. Production callers always supply now(); no browser accepts a clock.
create function startup_radar.weekly_schedule_plan(p_at timestamptz) returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare
 cfg jsonb; req startup_radar.weekly_schedule_requests;
 attempt startup_radar.weekly_dispatch_attempts; exec startup_radar.worker_executions;
 week date := date_trunc('week',p_at at time zone 'Asia/Seoul')::date;
 due timestamptz; state text; active_from date; enabled boolean;
begin
 due := (week+interval '1 day 9 hours') at time zone 'Asia/Seoul';
 select value into cfg from startup_radar.runtime_settings where key='weekly_scheduler';
 enabled := coalesce(cfg->'enabled'='true'::jsonb,false);
 active_from := nullif(cfg->>'active_from_week','')::date;
 select * into req from startup_radar.weekly_schedule_requests where week_start=week;
 select * into attempt from startup_radar.weekly_dispatch_attempts where request_id=req.id order by attempt_number desc limit 1;
 if req.execution_id is not null then
  select * into exec from startup_radar.worker_executions where id=req.execution_id;
 else
  -- Existing legacy/manual owners also suppress dispatch, even without a new
  -- correlation ID. Uncertain owners NEVER age out and are never auto-replaced.
  select * into exec from startup_radar.worker_executions
   where finished_at is null or (kind='WEEKLY' and started_at>=due and started_at<p_at+interval '1 microsecond')
   order by (finished_at is null) desc,started_at desc limit 1;
 end if;
 if exists(select 1 from startup_radar.weekly_briefings where week_start=week
           and publication_kind='WEEKLY' and status='PUBLISHED') then state := 'PUBLISHED';
 elsif exec.finished_at is null and exec.id is not null then
  state := case when exec.kind<>'WEEKLY' or exec.started_at<(week::timestamp at time zone 'Asia/Seoul') then 'BLOCKED_RUNNING'
                when p_at-exec.started_at>=interval '60 minutes' then 'LONG_RUNNING' else 'RUNNING' end;
 elsif exec.state in ('FAILED','PARTIAL_SUCCESS') then state := 'FAILED';
 elsif exec.state in ('UNCERTAIN','ABANDONED') or exec.id is not null then state := 'UNCERTAIN';
 elsif not enabled then state := 'DISABLED';
 elsif active_from is null then state := 'CONFIGURATION_ERROR';
 elsif week<active_from or p_at<due then state := 'NOT_DUE';
 elsif req.suppressed_reason is not null then state := 'SKIPPED_PAUSED';
 elsif (select value->'enabled' from startup_radar.runtime_settings where key='radar_operation')='false'::jsonb then state := 'PAUSED';
 elsif attempt.response_state='REJECTED' then state := 'DISPATCH_REJECTED';
 elsif attempt.id is not null and p_at-attempt.requested_at<interval '10 minutes' then state := 'DISPATCH_PENDING';
 elsif attempt.attempt_number>=3 then state := 'RETRY_EXHAUSTED';
 elsif attempt.id is not null then state := 'DISPATCH_DELAYED';
 else state := 'READY';
 end if;
 return jsonb_build_object('source','SUPABASE_CRON','enabled',enabled,'registered',startup_radar.weekly_cron_registered(),
   'checked_at',cfg->'last_tick_at','last_tick_state',cfg->'last_tick_state','active_from_week',active_from,'state',state,
   'dispatch_grace_seconds',600,'heartbeat_stale_after_seconds',900,'long_running_after_seconds',3600,
   'request',case when req.id is not null then jsonb_build_object('id',req.id,'week_start',req.week_start,
     'scheduled_at',req.scheduled_at,'created_at',req.created_at,'execution_id',req.execution_id) end,
   'latest_attempt',case when attempt.id is not null then jsonb_build_object('number',attempt.attempt_number,
     'requested_at',attempt.requested_at,'response_state',attempt.response_state,
     'responded_at',attempt.responded_at,'http_status',attempt.http_status) end);
end $$;

-- The target is fixed. A caller cannot redirect the Vault credential to an
-- arbitrary URL/ref/workflow. The durable attempt ledger never stores headers,
-- token or response bodies. pg_net's transient request queue contains headers;
-- activation restricts access to that provider-owned queue.
create function startup_radar.weekly_dispatch_http(p_id uuid,p_week date) returns bigint
language plpgsql security definer set search_path='' as $$
declare token text; request_id bigint;
begin
 if to_regprocedure('net.http_post(text,jsonb,jsonb,jsonb,integer)') is null
   or to_regclass('vault.decrypted_secrets') is null then return null; end if;
 execute 'select decrypted_secret from vault.decrypted_secrets where name=$1'
  into token using 'startup_radar_github_dispatch';
 if token is null or btrim(token)='' then return null; end if;
 execute $q$select net.http_post(
   url := 'https://api.github.com/repos/jey24960-sketch/startup-radar/actions/workflows/startup_radar_v2.yml/dispatches',
   body := jsonb_build_object('ref','main','inputs',jsonb_build_object('kind','WEEKLY',
       'scheduler_request_id',$1::text,'expected_week_start',$2::text)),
   headers := jsonb_build_object('Authorization','Bearer '||$3,'Accept','application/vnd.github+json',
       'X-GitHub-Api-Version','2022-11-28','Content-Type','application/json','User-Agent','GFC-weekly-scheduler'),
   timeout_milliseconds := 10000)$q$ into request_id using p_id,p_week,token;
 return request_id;
end $$;

create function startup_radar.weekly_dispatch_collect_responses(p_at timestamptz) returns void
language plpgsql security definer set search_path='' as $$
begin
 if to_regclass('net._http_response') is not null then
  execute $q$update startup_radar.weekly_dispatch_attempts a set
    response_state=case when r.status_code=204 then 'ACCEPTED'
      when r.timed_out or r.error_msg is not null or r.status_code is null then 'UNKNOWN'
      when r.status_code in (408,429) or r.status_code>=500 then 'RETRYABLE' else 'REJECTED' end,
    http_status=r.status_code,responded_at=r.created
   from net._http_response r where a.http_request_id=r.id and a.response_state in ('PENDING','UNKNOWN')$q$;
 end if;
 -- pg_net queues/responses are unlogged. Missing acknowledgements stay unknown,
 -- never successful; retry uses the SAME durable request identity.
 update startup_radar.weekly_dispatch_attempts set response_state='UNKNOWN'
  where response_state='PENDING' and p_at-requested_at>=interval '10 minutes';
end $$;

create function startup_radar.weekly_scheduler_tick_at(p_at timestamptz) returns jsonb
language plpgsql security definer set search_path='' as $$
declare plan jsonb; cfg jsonb; req startup_radar.weekly_schedule_requests;
 week date := date_trunc('week',p_at at time zone 'Asia/Seoul')::date;
 due timestamptz; http_id bigint; number integer; state text;
begin
 -- The same short lock as worker claims prevents a dispatch decision racing a
 -- just-starting legacy/manual execution. No network is awaited under the lock.
 if not pg_try_advisory_xact_lock(782394202) then return jsonb_build_object('state','CLAIM_BUSY'); end if;
 perform startup_radar.weekly_dispatch_collect_responses(p_at);
 plan := startup_radar.weekly_schedule_plan(p_at); state := plan->>'state';
 due := (week+interval '1 day 9 hours') at time zone 'Asia/Seoul';
 if state in ('READY','DISPATCH_DELAYED','PAUSED') then
  insert into startup_radar.weekly_schedule_requests(week_start,scheduled_at,created_at,suppressed_reason)
   values(week,due,p_at,case when state='PAUSED' then 'OPERATOR_PAUSED' end)
   on conflict(week_start) do nothing;
  select * into req from startup_radar.weekly_schedule_requests where week_start=week for update;
  if state='PAUSED' then
   update startup_radar.weekly_schedule_requests set suppressed_reason='OPERATOR_PAUSED'
    where id=req.id and execution_id is null;
  elsif req.execution_id is null and req.suppressed_reason is null then
   select coalesce(max(attempt_number),0)+1 into number from startup_radar.weekly_dispatch_attempts where request_id=req.id;
   if number<=3 then
    begin
     http_id := startup_radar.weekly_dispatch_http(req.id,week);
     if http_id is null then state := 'CONFIGURATION_ERROR';
     else
      insert into startup_radar.weekly_dispatch_attempts(request_id,attempt_number,http_request_id,requested_at)
       values(req.id,number,http_id,p_at);
      state := 'DISPATCH_PENDING';
     end if;
    exception when others then
     -- Do not include SQLERRM: provider errors may contain credential headers.
     state := 'CONFIGURATION_ERROR';
    end;
   end if;
  end if;
 end if;
 update startup_radar.runtime_settings set value=value||jsonb_build_object('last_tick_at',p_at,'last_tick_state',state)
  where key='weekly_scheduler';
 return jsonb_build_object('state',state,'week_start',week);
end $$;

create function startup_radar.weekly_scheduler_tick() returns jsonb
language sql security definer set search_path='' as $$
 select startup_radar.weekly_scheduler_tick_at(now());
$$;

create function startup_radar.configure_weekly_scheduler(p_enabled boolean,p_active_from_week date,p_note text) returns jsonb
language plpgsql security definer set search_path='' as $$
declare value jsonb; due timestamptz;
begin
 if p_enabled is null or length(btrim(coalesce(p_note,''))) not between 5 and 500 then
  raise exception 'Explicit switch and an operational note are required';
 end if;
 perform pg_advisory_xact_lock(782394202);
 if p_enabled then
  if p_active_from_week is null or extract(isodow from p_active_from_week)<>1 then raise exception 'A Monday activation week is required'; end if;
  due := (p_active_from_week+interval '1 day 9 hours') at time zone 'Asia/Seoul';
  if due<=now() then raise exception 'Activation must begin before its future due time; no implicit catch-up'; end if;
  if not startup_radar.weekly_cron_registered() then raise exception 'Register the approved active cron job before enabling dispatch'; end if;
 end if;
 update startup_radar.runtime_settings s set value=s.value||jsonb_build_object('enabled',p_enabled,
   'active_from_week',p_active_from_week,'updated_at',now(),'version',coalesce((s.value->>'version')::integer,0)+1)
  where key='weekly_scheduler' returning s.value into value;
 insert into startup_radar.admin_audit(action,entity_id,detail)
  values('WEEKLY_SCHEDULER_CONFIGURED','weekly_scheduler',jsonb_build_object('enabled',p_enabled,
    'active_from_week',p_active_from_week,'note',btrim(p_note)));
 return value - 'last_tick_at' - 'last_tick_state';
end $$;

revoke all on function startup_radar.weekly_cron_registered(),startup_radar.weekly_schedule_plan(timestamptz),
 startup_radar.weekly_dispatch_http(uuid,date),startup_radar.weekly_dispatch_collect_responses(timestamptz),
 startup_radar.weekly_scheduler_tick_at(timestamptz),startup_radar.weekly_scheduler_tick(),
 startup_radar.configure_weekly_scheduler(boolean,date,text) from public,anon,authenticated,service_role;
grant execute on function startup_radar.weekly_scheduler_tick(),startup_radar.configure_weekly_scheduler(boolean,date,text) to service_role;

-- Preserve every previous response key/permission, and append observed runtime.
-- The approved timetable is Tuesday 09:00 KST. Override only timetable values
-- from the historical base projection; all observed records remain unchanged.
-- The original function was introduced by the separately reviewed admin change.
alter function public.gfc_radar_admin_weekly_status() rename to gfc_radar_admin_weekly_status_base;
revoke all on function public.gfc_radar_admin_weekly_status_base() from public,anon,authenticated,service_role;
create function public.gfc_radar_admin_weekly_status() returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare result jsonb; due timestamptz;
begin
 perform startup_radar.require_admin();
 result := public.gfc_radar_admin_weekly_status_base();
 due := ((result->>'week_start')::date+interval '1 day 9 hours') at time zone 'Asia/Seoul';
 result := result || jsonb_build_object('scheduled_at',due,
  'next_scheduled_at',case when now()<due then due else due+interval '7 days' end);
 return jsonb_set(result,'{schedule,runtime}',startup_radar.weekly_schedule_plan(now()),true);
end $$;
revoke all on function public.gfc_radar_admin_weekly_status() from public,anon,authenticated;
grant execute on function public.gfc_radar_admin_weekly_status() to authenticated,service_role;
notify pgrst,'reload schema';
commit;
