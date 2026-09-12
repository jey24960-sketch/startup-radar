-- Runtime jobs, relational integrity and immutable notification batches.
alter table radar.telegram_subscriptions add constraint subscription_team_unique unique(id,team_id);
alter table radar.notification_items add constraint notification_subscription_team_fk
 foreign key(subscription_id,team_id) references radar.telegram_subscriptions(id,team_id);
alter table radar.documents add constraint document_version_unique unique(id,program_version_id);
alter table radar.program_requirements add constraint requirement_document_version_fk
 foreign key(document_id,program_version_id) references radar.documents(id,program_version_id);
create index documents_version_idx on radar.documents(program_version_id);
create index program_sources_url_idx on radar.program_sources(official_detail_url);
create index versions_program_idx on radar.program_versions(program_id,created_at desc);
create index source_results_run_idx on radar.source_run_results(run_id);

alter table radar.notification_items drop constraint notification_items_state_check;
alter table radar.notification_items add constraint notification_items_state_check
 check(state in ('PENDING','SENDING','DELIVERED','FAILED','UNCERTAIN','CANCELLED'));
create table radar.notification_batches (
 id uuid primary key default gen_random_uuid(), subscription_id uuid not null references radar.telegram_subscriptions,
 kind text not null check(kind in ('DIGEST','HIGH_FIT','REMINDER')),
 dedupe_key text not null unique, state text not null check(state in ('PENDING','SENDING','DELIVERED','FAILED','UNCERTAIN','CANCELLED')),
 payload jsonb not null default '{}', receipt jsonb, error text, attempts integer not null default 0,
 created_at timestamptz not null default now(), claimed_at timestamptz, delivered_at timestamptz
);
alter table radar.notification_items add column batch_id uuid references radar.notification_batches;
create index notification_batches_queue_idx on radar.notification_batches(state,created_at);
create index notification_items_batch_idx on radar.notification_items(batch_id);
create table radar.job_requests (
 id uuid primary key default gen_random_uuid(), kind text not null check(kind in ('INGEST','DIGEST','REMINDER','HIGH_FIT','TICK')),
 source_slug text, requested_by uuid references auth.users, state text not null default 'REQUESTED'
 check(state in ('REQUESTED','RUNNING','SUCCESS','PARTIAL_SUCCESS','FAILED','UNCERTAIN')),
 result jsonb, created_at timestamptz not null default now(), finished_at timestamptz
);
create table radar.schedule_claims (
 task_key text primary key, kind text not null, state text not null check(state in ('RUNNING','SUCCESS','PARTIAL_SUCCESS','FAILED','UNCERTAIN')),
 created_at timestamptz not null default now(), finished_at timestamptz, result jsonb
);
create table radar.admin_audit (
 id uuid primary key default gen_random_uuid(), actor_id uuid references auth.users,
 action text not null, entity_id text, detail jsonb not null default '{}', created_at timestamptz not null default now()
);
insert into radar.runtime_settings(key,value) values
 ('notification_policy','{"digest_limit":5,"high_fit_daily_limit":2,"high_fit_min_days":3,"high_fit_new_days":7,"delivery_batch_limit":30}'),
 ('recommendation_weights','{"stage":25,"profile":20,"preference":15,"benefit":10,"global":10,"runway":10,"completeness":10}')
on conflict(key) do nothing;

alter table radar.notification_batches enable row level security;
alter table radar.job_requests enable row level security;
alter table radar.schedule_claims enable row level security;
alter table radar.admin_audit enable row level security;
grant all on radar.notification_batches,radar.job_requests,radar.schedule_claims,radar.admin_audit to service_role;
grant select on radar.notification_batches,radar.job_requests,radar.schedule_claims,radar.admin_audit to authenticated;
create policy read_batches on radar.notification_batches for select to authenticated using(exists(select 1 from radar.admin_users a where a.user_id=(select auth.uid())));
create policy read_jobs on radar.job_requests for select to authenticated using(exists(select 1 from radar.admin_users a where a.user_id=(select auth.uid())));
create policy read_claims on radar.schedule_claims for select to authenticated using(exists(select 1 from radar.admin_users a where a.user_id=(select auth.uid())));
create policy read_audit on radar.admin_audit for select to authenticated using(exists(select 1 from radar.admin_users a where a.user_id=(select auth.uid())));
alter table radar.telegram_admins add column selected_team_id uuid references radar.teams;
