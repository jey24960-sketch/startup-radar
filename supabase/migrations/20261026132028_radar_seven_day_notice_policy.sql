-- Internal twice-daily facts collection; member publication stays weekly.
create table startup_radar.discovery_slots (
 slot_start timestamptz primary key,
 execution_id uuid not null unique references startup_radar.worker_executions(id),
 created_at timestamptz not null default now(),
 finished_at timestamptz,
 result jsonb
);
alter table startup_radar.discovery_slots enable row level security;
revoke all on startup_radar.discovery_slots from public,anon,authenticated;
grant all on startup_radar.discovery_slots to service_role;

insert into startup_radar.runtime_settings(key,value) values
 ('daily_discovery','{"enabled":false,"kstartup_max_pages":10,"bizinfo_max_pages":20}'::jsonb),
 ('notice_policy','{"enabled":false,"minimum_lead_days":7}'::jsonb)
on conflict(key) do nothing;

create index program_source_latest_candidate_idx on startup_radar.program_source_snapshots
 (program_id,source_id,observed_at desc,id desc);
create index program_sources_fresh_candidates_idx on startup_radar.program_sources(last_seen_at);

-- An additive DB guard protects the rule even if an older worker is invoked.
-- Rollout enables this only after code/schema verification and historical cleanup.
create function startup_radar.has_notice_preparation_time(facts jsonb,reference_at timestamptz)
returns boolean language plpgsql immutable security invoker set search_path='' as $$
declare deadline timestamptz; starts timestamptz;
begin
 if reference_at is null or nullif(facts->>'application_end_at','') is null then return false; end if;
 if facts->>'application_end_at' !~ '(Z|[+-][0-9]{2}:[0-9]{2})$' then return false; end if;
 deadline:=(facts->>'application_end_at')::timestamptz;
 if nullif(facts->>'application_start_at','') is not null then
  starts:=(facts->>'application_start_at')::timestamptz;
  if starts>deadline then return false; end if;
 end if;
 return deadline>=reference_at+interval '7 days';
exception when invalid_datetime_format or datetime_field_overflow then return false;
end $$;
revoke all on function startup_radar.has_notice_preparation_time(jsonb,timestamptz) from public,anon,authenticated;
grant execute on function startup_radar.has_notice_preparation_time(jsonb,timestamptz) to service_role;

create function startup_radar.enforce_weekly_preparation_time()
returns trigger language plpgsql security invoker set search_path='' as $$
declare enabled boolean;
begin
 select coalesce((value->>'enabled')::boolean,false) into enabled
 from startup_radar.runtime_settings where key='notice_policy';
 if not coalesce(enabled,false) then return new; end if;
 if new.status='PUBLISHED' and (tg_op='INSERT' or old.status is distinct from 'PUBLISHED') then
  if new.published_at is null then raise exception 'Publication clock required'; end if;
  if exists(select 1 from startup_radar.weekly_briefing_items i where i.briefing_id=new.id
    and not startup_radar.has_notice_preparation_time(i.snapshot,new.published_at)) then
   raise exception 'Every published opportunity requires at least seven days before its deadline';
  end if;
 end if;
 return new;
end $$;
revoke all on function startup_radar.enforce_weekly_preparation_time() from public,anon,authenticated;
create trigger weekly_preparation_time_guard before insert or update of status,published_at
 on startup_radar.weekly_briefings for each row execute function startup_radar.enforce_weekly_preparation_time();

create function startup_radar.enforce_published_item_preparation_time()
returns trigger language plpgsql security invoker set search_path='' as $$
declare enabled boolean; publication startup_radar.weekly_briefings%rowtype;
begin
 select coalesce((value->>'enabled')::boolean,false) into enabled
 from startup_radar.runtime_settings where key='notice_policy';
 if not coalesce(enabled,false) then return new; end if;
 if tg_op='UPDATE' and new.snapshot is not distinct from old.snapshot then return new; end if;
 select * into publication from startup_radar.weekly_briefings where id=new.briefing_id;
 if publication.status='PUBLISHED' and not startup_radar.has_notice_preparation_time(new.snapshot,greatest(publication.published_at,now())) then
  raise exception 'A newly inserted or revised notice item requires seven days of preparation';
 end if;
 return new;
end $$;
revoke all on function startup_radar.enforce_published_item_preparation_time() from public,anon,authenticated;
create trigger published_item_preparation_time_guard before insert or update of snapshot
 on startup_radar.weekly_briefing_items for each row execute function startup_radar.enforce_published_item_preparation_time();

comment on table startup_radar.discovery_slots is 'Internal collection slots. No daily member digest; a slot is never silently retried after uncertain ownership.';
comment on function startup_radar.has_notice_preparation_time(jsonb,timestamptz) is 'Seven-day publication gate against known source dates; never infers a missing deadline.';
