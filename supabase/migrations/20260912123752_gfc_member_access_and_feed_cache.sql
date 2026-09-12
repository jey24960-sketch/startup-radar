-- GFC integration: existing membership is authoritative. No GFC object altered.
begin;
set local lock_timeout='2s';
set local statement_timeout='30s';
-- Fail closed when this migration is accidentally applied outside the shared GFC DB.
do $$ begin
 if to_regprocedure('public.my_role()') is null then
   raise exception 'Existing GFC public.my_role() is required';
 end if;
end $$;
-- Restrictive policies are ANDed with all existing permissive policies.
do $$ declare t record; begin
 for t in select tablename from pg_tables where schemaname='startup_radar' loop
  execute format('create policy gfc_verified_member on startup_radar.%I as restrictive for all to authenticated using ((select public.my_role()) in (''member'',''admin'')) with check ((select public.my_role()) in (''member'',''admin''))',t.tablename);
 end loop;
end $$;
-- Stage 0 requires GFC membership, not a pre-existing Radar team.
alter policy read_programs on startup_radar.programs using ((select public.my_role()) in ('member','admin'));
alter policy read_program_versions on startup_radar.program_versions using ((select public.my_role()) in ('member','admin'));
alter policy read_documents on startup_radar.documents using ((select public.my_role()) in ('member','admin'));
alter policy read_program_requirements on startup_radar.program_requirements using ((select public.my_role()) in ('member','admin'));
alter policy read_program_change_events on startup_radar.program_change_events using ((select public.my_role()) in ('member','admin'));

create table startup_radar.feed_snapshots (
 scope_key text not null,
 program_id uuid not null references startup_radar.programs on delete cascade,
 program_version_id uuid not null references startup_radar.program_versions on delete cascade,
 team_id uuid references startup_radar.teams on delete cascade,
 preset integer check(preset between 0 and 4),
 cache_key text not null,
 payload jsonb not null,
 eligibility_status text not null check(eligibility_status in ('ELIGIBLE','NEEDS_INFO','INELIGIBLE','UNVERIFIABLE')),
 program_status text not null check(program_status in ('OPEN','UPCOMING','CLOSED','UNKNOWN')),
 score numeric,
 refreshed_at timestamptz not null default now(),
 primary key(scope_key,program_id,cache_key),
 check ((team_id is not null and preset is null and scope_key=team_id::text)
     or (team_id is null and preset is not null and scope_key='preset:'||preset::text))
);
create index feed_snapshots_team_idx on startup_radar.feed_snapshots(team_id);
create index feed_snapshots_version_idx on startup_radar.feed_snapshots(program_version_id);
create index feed_snapshots_program_idx on startup_radar.feed_snapshots(program_id);
create index feed_snapshots_browse_idx on startup_radar.feed_snapshots(scope_key,cache_key,program_status,eligibility_status,score desc);
alter table startup_radar.feed_snapshots enable row level security;
revoke all on startup_radar.feed_snapshots from public,anon,authenticated;
grant select on startup_radar.feed_snapshots to authenticated;
grant all on startup_radar.feed_snapshots to service_role;
create policy read_feed_snapshots on startup_radar.feed_snapshots for select to authenticated using (
 (select public.my_role()) in ('member','admin') and
 (team_id is null or team_id in (select m.team_id from startup_radar.team_members m where m.user_id=(select auth.uid())))
);
create table startup_radar.extraction_cache (
 input_hash text primary key, normalized jsonb not null, metadata jsonb not null,
 created_at timestamptz not null default now()
);
alter table startup_radar.extraction_cache enable row level security;
revoke all on startup_radar.extraction_cache from public,anon,authenticated;
grant all on startup_radar.extraction_cache to service_role;
-- Preferences can be saved before a Telegram channel is linked.
create table startup_radar.team_notification_preferences (
 team_id uuid primary key references startup_radar.teams on delete cascade,
 enabled boolean not null default true,
 digest_enabled boolean not null default true,
 alerts_enabled boolean not null default true,
 reminders_enabled boolean not null default true
);
alter table startup_radar.team_notification_preferences enable row level security;
revoke all on startup_radar.team_notification_preferences from public,anon,authenticated;
grant select,insert,update on startup_radar.team_notification_preferences to authenticated;
grant all on startup_radar.team_notification_preferences to service_role;
create policy read_team_preferences on startup_radar.team_notification_preferences for select to authenticated using (
 (select public.my_role()) in ('member','admin') and team_id in (select m.team_id from startup_radar.team_members m where m.user_id=(select auth.uid())));
create policy update_team_preferences on startup_radar.team_notification_preferences for update to authenticated using (
 (select public.my_role()) in ('member','admin') and team_id in (select m.team_id from startup_radar.team_members m where m.user_id=(select auth.uid()) and m.role in ('OWNER','EDITOR')))
 with check ((select public.my_role()) in ('member','admin') and team_id in (select m.team_id from startup_radar.team_members m where m.user_id=(select auth.uid()) and m.role in ('OWNER','EDITOR')));
create policy insert_team_preferences on startup_radar.team_notification_preferences for insert to authenticated
 with check ((select public.my_role()) in ('member','admin') and team_id in (select m.team_id from startup_radar.team_members m where m.user_id=(select auth.uid()) and m.role in ('OWNER','EDITOR')));
commit;
