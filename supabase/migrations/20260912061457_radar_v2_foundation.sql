-- StartupRadar V2 isolated schema; auth.users is provided by Supabase.
create schema if not exists radar;
grant usage on schema radar to authenticated, service_role;

create table radar.teams (
 id uuid primary key default gen_random_uuid(), name text not null check(length(name) between 1 and 100),
 created_at timestamptz not null default now()
);
create table radar.team_members (
 team_id uuid not null references radar.teams on delete cascade,
 user_id uuid not null references auth.users on delete cascade,
 role text not null check(role in ('OWNER','EDITOR','MEMBER')),
 created_at timestamptz not null default now(), primary key(team_id,user_id)
);
create index team_members_user_idx on radar.team_members(user_id,team_id);
create table radar.admin_users (user_id uuid primary key references auth.users on delete cascade);
create table radar.team_profiles (
 team_id uuid primary key references radar.teams on delete cascade,
 profile jsonb not null default '{}' check(jsonb_typeof(profile)='object'),
 version integer not null default 1 check(version>0), updated_at timestamptz not null default now()
);
create table radar.team_profile_versions (
 id uuid primary key default gen_random_uuid(), team_id uuid not null references radar.teams,
 version integer not null check(version>0), profile jsonb not null check(jsonb_typeof(profile)='object'),
 created_at timestamptz not null default now(), unique(team_id,version), unique(id,team_id)
);
create table radar.sources (
 id uuid primary key default gen_random_uuid(), slug text not null unique, name text not null,
 adapter text not null check(adapter in ('KSTARTUP','BIZINFO','RSS','HTML','BROWSER','SEARCH')),
 config jsonb not null default '{}', enabled boolean not null default true,
 last_attempted_at timestamptz, last_successful_at timestamptz,
 created_at timestamptz not null default now()
);
create table radar.ingestion_runs (
 id uuid primary key default gen_random_uuid(), status text not null check(status in ('RUNNING','SUCCESS','PARTIAL_SUCCESS','FAILED')),
 started_at timestamptz not null default now(), finished_at timestamptz,
 trigger_type text not null, summary jsonb not null default '{}'
);
create table radar.source_run_results (
 id uuid primary key default gen_random_uuid(), run_id uuid not null references radar.ingestion_runs,
 source_id uuid not null references radar.sources, status text not null check(status in ('SUCCESS','PARTIAL','FAILED')),
 discovered_count integer not null default 0 check(discovered_count>=0), fetched_count integer not null default 0 check(fetched_count>=0),
 parsed_count integer not null default 0 check(parsed_count>=0), failures jsonb not null default '[]',
 latency_ms integer not null default 0 check(latency_ms>=0), created_at timestamptz not null default now(), unique(run_id,source_id)
);
create index source_results_history_idx on radar.source_run_results(source_id,created_at desc);
create table radar.programs (
 id uuid primary key default gen_random_uuid(), canonical_key text not null unique,
 title text not null, organization text not null, program_types text[] not null default '{}',
 status text not null check(status in ('OPEN','UPCOMING','CLOSED','UNKNOWN')),
 application_start_at timestamptz, application_end_at timestamptz,
 deadline_type text not null check(deadline_type in ('FIXED_DATE','ROLLING','UNTIL_BUDGET_EXHAUSTED','UNKNOWN')),
 official_url text not null, application_url text, region_requirements jsonb not null default '[]',
 applicant_summary text, support_summary text, benefit_summary text,
 amount_min numeric, amount_max numeric, currency text not null default 'KRW',
 current_version_id uuid, created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
 check(amount_min is null or amount_max is null or amount_min<=amount_max),
 check(application_start_at is null or application_end_at is null or application_start_at<=application_end_at)
);
create index programs_browse_idx on radar.programs(status,application_end_at);
create index programs_types_idx on radar.programs using gin(program_types);
create table radar.program_sources (
 id uuid primary key default gen_random_uuid(), program_id uuid not null references radar.programs,
 source_id uuid not null references radar.sources, source_program_id text,
 discovery_url text not null, official_detail_url text, raw_metadata jsonb not null default '{}',
 discovered_at timestamptz not null default now(), last_seen_at timestamptz not null default now(),
 unique(source_id,source_program_id), unique(source_id,discovery_url)
);
create index program_sources_program_idx on radar.program_sources(program_id);
create table radar.program_versions (
 id uuid primary key default gen_random_uuid(), program_id uuid not null references radar.programs,
 version integer not null check(version>0), content_hash text not null,
 normalized jsonb not null, raw_text text not null default '', evidence_complete boolean not null default false,
 created_at timestamptz not null default now(), unique(program_id,version), unique(id,program_id)
);
alter table radar.programs add constraint programs_current_version_fk foreign key(current_version_id,id)
 references radar.program_versions(id,program_id) deferrable initially deferred;
create table radar.documents (
 id uuid primary key default gen_random_uuid(), program_version_id uuid not null references radar.program_versions,
 original_url text not null, filename text not null, detected_mime text, content_hash text,
 fetch_status text not null check(fetch_status in ('PENDING','SUCCESS','FAILED','BLOCKED')),
 extraction_status text not null check(extraction_status in ('PENDING','SUCCESS','FAILED','UNSUPPORTED')),
 extracted_text text, error_kind text, error_message text, fetched_at timestamptz,
 unique(program_version_id,original_url)
);
create table radar.program_requirements (
 id uuid primary key default gen_random_uuid(), program_version_id uuid not null references radar.program_versions,
 document_id uuid references radar.documents, requirement jsonb not null,
 created_at timestamptz not null default now()
);
create index requirements_version_idx on radar.program_requirements(program_version_id);
create table radar.possible_duplicates (
 id uuid primary key default gen_random_uuid(), program_id uuid not null references radar.programs,
 candidate_program_id uuid not null references radar.programs, confidence numeric not null check(confidence between 0 and 1),
 reason text not null, state text not null default 'PENDING' check(state in ('PENDING','CONFIRMED','REJECTED')),
 created_at timestamptz not null default now(), check(program_id<>candidate_program_id), unique(program_id,candidate_program_id)
);
create table radar.eligibility_evaluations (
 id uuid primary key default gen_random_uuid(), team_id uuid not null references radar.teams,
 profile_version_id uuid not null, program_version_id uuid not null references radar.program_versions,
 status text not null check(status in ('ELIGIBLE','NEEDS_INFO','INELIGIBLE','UNVERIFIABLE')),
 result jsonb not null, engine_version text not null, evaluated_at timestamptz not null default now(),
 foreign key(profile_version_id,team_id) references radar.team_profile_versions(id,team_id), unique(id,team_id)
);
create index evaluations_team_idx on radar.eligibility_evaluations(team_id,program_version_id,evaluated_at desc);
create table radar.recommendations (
 id uuid primary key default gen_random_uuid(), team_id uuid not null references radar.teams,
 evaluation_id uuid not null, score numeric not null check(score between 0 and 100),
 components jsonb not null, provider text not null, model text, prompt_version text not null, schema_version text not null,
 explanation text not null, created_at timestamptz not null default now(),
 foreign key(evaluation_id,team_id) references radar.eligibility_evaluations(id,team_id), unique(id,team_id)
);
create index recommendations_team_idx on radar.recommendations(team_id,score desc);
create table radar.program_change_events (
 id uuid primary key default gen_random_uuid(), program_id uuid not null references radar.programs,
 version_id uuid not null references radar.program_versions, event_type text not null check(event_type in ('NEW','UPDATE')),
 changed_fields text[] not null, created_at timestamptz not null default now(), unique(version_id)
);
create table radar.telegram_subscriptions (
 id uuid primary key default gen_random_uuid(), team_id uuid not null references radar.teams,
 chat_id text not null, enabled boolean not null default true, digest_enabled boolean not null default true,
 alerts_enabled boolean not null default true, reminders_enabled boolean not null default true,
 high_fit_threshold numeric not null default 90 check(high_fit_threshold between 0 and 100),
 reminder_days integer[] not null default '{7,3}', created_at timestamptz not null default now(), unique(team_id,chat_id)
);
create table radar.notification_runs (
 id uuid primary key default gen_random_uuid(), kind text not null check(kind in ('DIGEST','HIGH_FIT','REMINDER')),
 status text not null check(status in ('RUNNING','SUCCESS','PARTIAL_SUCCESS','FAILED')),
 started_at timestamptz not null default now(), finished_at timestamptz
);
create table radar.notification_items (
 id uuid primary key default gen_random_uuid(), run_id uuid references radar.notification_runs,
 subscription_id uuid not null references radar.telegram_subscriptions,
 team_id uuid not null references radar.teams, program_version_id uuid not null references radar.program_versions,
 recommendation_id uuid, dedupe_key text not null unique,
 kind text not null check(kind in ('DIGEST','HIGH_FIT','REMINDER')),
 state text not null check(state in ('PENDING','SENDING','DELIVERED','FAILED','UNCERTAIN')),
 payload jsonb not null, delivery_receipts jsonb not null default '[]', attempts integer not null default 0,
 delivered_at timestamptz, error text, created_at timestamptz not null default now(),
 foreign key(recommendation_id,team_id) references radar.recommendations(id,team_id)
);
create index notification_queue_idx on radar.notification_items(state,created_at);
create table radar.runtime_settings (
 key text primary key, value jsonb not null, updated_at timestamptz not null default now()
);
insert into radar.runtime_settings(key,value) values
 ('scheduling','{"ingestion_enabled":true,"ingestion_hour":6,"digest_weekday":1,"digest_hour":15,"reminder_hour":15,"timezone":"Asia/Seoul"}');
create table radar.telegram_updates (
 update_id bigint primary key, state text not null check(state in ('PROCESSING','COMPLETED','FAILED','UNCERTAIN')),
 result jsonb, created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create table radar.telegram_admins (
 telegram_user_id text primary key, user_id uuid not null references auth.users, created_at timestamptz not null default now()
);
alter table radar.teams enable row level security;
grant all on radar.teams to service_role;
alter table radar.team_members enable row level security;
grant all on radar.team_members to service_role;
alter table radar.admin_users enable row level security;
grant all on radar.admin_users to service_role;
alter table radar.team_profiles enable row level security;
grant all on radar.team_profiles to service_role;
alter table radar.team_profile_versions enable row level security;
grant all on radar.team_profile_versions to service_role;
alter table radar.sources enable row level security;
grant all on radar.sources to service_role;
alter table radar.ingestion_runs enable row level security;
grant all on radar.ingestion_runs to service_role;
alter table radar.source_run_results enable row level security;
grant all on radar.source_run_results to service_role;
alter table radar.programs enable row level security;
grant all on radar.programs to service_role;
alter table radar.program_sources enable row level security;
grant all on radar.program_sources to service_role;
alter table radar.program_versions enable row level security;
grant all on radar.program_versions to service_role;
alter table radar.documents enable row level security;
grant all on radar.documents to service_role;
alter table radar.program_requirements enable row level security;
grant all on radar.program_requirements to service_role;
alter table radar.possible_duplicates enable row level security;
grant all on radar.possible_duplicates to service_role;
alter table radar.eligibility_evaluations enable row level security;
grant all on radar.eligibility_evaluations to service_role;
alter table radar.recommendations enable row level security;
grant all on radar.recommendations to service_role;
alter table radar.program_change_events enable row level security;
grant all on radar.program_change_events to service_role;
alter table radar.telegram_subscriptions enable row level security;
grant all on radar.telegram_subscriptions to service_role;
alter table radar.notification_runs enable row level security;
grant all on radar.notification_runs to service_role;
alter table radar.notification_items enable row level security;
grant all on radar.notification_items to service_role;
alter table radar.runtime_settings enable row level security;
grant all on radar.runtime_settings to service_role;
alter table radar.telegram_updates enable row level security;
grant all on radar.telegram_updates to service_role;
alter table radar.telegram_admins enable row level security;
grant all on radar.telegram_admins to service_role;
grant select on radar.teams to authenticated;
create policy read_teams on radar.teams for select to authenticated using (id in (select m.team_id from radar.team_members m where m.user_id=(select auth.uid())));
grant select on radar.team_members to authenticated;
create policy read_team_members on radar.team_members for select to authenticated using (user_id=(select auth.uid()));
grant select on radar.admin_users to authenticated;
create policy read_admin_users on radar.admin_users for select to authenticated using (user_id=(select auth.uid()));
grant select on radar.team_profiles to authenticated;
create policy read_team_profiles on radar.team_profiles for select to authenticated using (team_id in (select m.team_id from radar.team_members m where m.user_id=(select auth.uid())));
grant select on radar.team_profile_versions to authenticated;
create policy read_team_profile_versions on radar.team_profile_versions for select to authenticated using (team_id in (select m.team_id from radar.team_members m where m.user_id=(select auth.uid())));
grant select on radar.sources to authenticated;
create policy read_sources on radar.sources for select to authenticated using (exists(select 1 from radar.admin_users a where a.user_id=(select auth.uid())));
grant select on radar.ingestion_runs to authenticated;
create policy read_ingestion_runs on radar.ingestion_runs for select to authenticated using (exists(select 1 from radar.admin_users a where a.user_id=(select auth.uid())));
grant select on radar.source_run_results to authenticated;
create policy read_source_run_results on radar.source_run_results for select to authenticated using (exists(select 1 from radar.admin_users a where a.user_id=(select auth.uid())));
grant select on radar.programs to authenticated;
create policy read_programs on radar.programs for select to authenticated using (exists(select 1 from radar.team_members m where m.user_id=(select auth.uid())));
grant select on radar.program_sources to authenticated;
create policy read_program_sources on radar.program_sources for select to authenticated using (exists(select 1 from radar.admin_users a where a.user_id=(select auth.uid())));
grant select on radar.program_versions to authenticated;
create policy read_program_versions on radar.program_versions for select to authenticated using (exists(select 1 from radar.team_members m where m.user_id=(select auth.uid())));
grant select on radar.documents to authenticated;
create policy read_documents on radar.documents for select to authenticated using (exists(select 1 from radar.team_members m where m.user_id=(select auth.uid())));
grant select on radar.program_requirements to authenticated;
create policy read_program_requirements on radar.program_requirements for select to authenticated using (exists(select 1 from radar.team_members m where m.user_id=(select auth.uid())));
grant select on radar.possible_duplicates to authenticated;
create policy read_possible_duplicates on radar.possible_duplicates for select to authenticated using (exists(select 1 from radar.admin_users a where a.user_id=(select auth.uid())));
grant select on radar.eligibility_evaluations to authenticated;
create policy read_eligibility_evaluations on radar.eligibility_evaluations for select to authenticated using (team_id in (select m.team_id from radar.team_members m where m.user_id=(select auth.uid())));
grant select on radar.recommendations to authenticated;
create policy read_recommendations on radar.recommendations for select to authenticated using (team_id in (select m.team_id from radar.team_members m where m.user_id=(select auth.uid())));
grant select on radar.program_change_events to authenticated;
create policy read_program_change_events on radar.program_change_events for select to authenticated using (exists(select 1 from radar.team_members m where m.user_id=(select auth.uid())));
grant select on radar.telegram_subscriptions to authenticated;
create policy read_telegram_subscriptions on radar.telegram_subscriptions for select to authenticated using (exists(select 1 from radar.admin_users a where a.user_id=(select auth.uid())));
grant select on radar.notification_runs to authenticated;
create policy read_notification_runs on radar.notification_runs for select to authenticated using (exists(select 1 from radar.admin_users a where a.user_id=(select auth.uid())));
grant select on radar.notification_items to authenticated;
create policy read_notification_items on radar.notification_items for select to authenticated using (exists(select 1 from radar.admin_users a where a.user_id=(select auth.uid())));
grant select on radar.runtime_settings to authenticated;
create policy read_runtime_settings on radar.runtime_settings for select to authenticated using (exists(select 1 from radar.admin_users a where a.user_id=(select auth.uid())));
grant select on radar.telegram_updates to authenticated;
create policy read_telegram_updates on radar.telegram_updates for select to authenticated using (exists(select 1 from radar.admin_users a where a.user_id=(select auth.uid())));
grant select on radar.telegram_admins to authenticated;
create policy read_telegram_admins on radar.telegram_admins for select to authenticated using (exists(select 1 from radar.admin_users a where a.user_id=(select auth.uid())));
grant insert on radar.team_profiles to authenticated;
create policy insert_team_profiles on radar.team_profiles for insert to authenticated with check (team_id in (select m.team_id from radar.team_members m where m.user_id=(select auth.uid()) and m.role in ('OWNER','EDITOR')));
grant insert on radar.team_profile_versions to authenticated;
create policy insert_team_profile_versions on radar.team_profile_versions for insert to authenticated with check (team_id in (select m.team_id from radar.team_members m where m.user_id=(select auth.uid()) and m.role in ('OWNER','EDITOR')));
grant update on radar.team_profiles to authenticated;
create policy update_profiles on radar.team_profiles for update to authenticated using (team_id in (select m.team_id from radar.team_members m where m.user_id=(select auth.uid()) and m.role in ('OWNER','EDITOR'))) with check (team_id in (select m.team_id from radar.team_members m where m.user_id=(select auth.uid()) and m.role in ('OWNER','EDITOR')));
