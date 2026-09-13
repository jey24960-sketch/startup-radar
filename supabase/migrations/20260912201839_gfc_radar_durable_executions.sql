-- Durable global batch ownership. No long-lived connection or automatic expiry.
set local lock_timeout='2s';
set local statement_timeout='30s';
create table startup_radar.worker_executions (
 id uuid primary key,
 kind text not null check(kind in ('INGEST','DIGEST','REMINDER','HIGH_FIT','TICK','REFRESH')),
 source_slug text,
 job_id uuid references startup_radar.job_requests(id) on delete set null,
 state text not null default 'RUNNING' check(state in ('RUNNING','SUCCESS','PARTIAL_SUCCESS','FAILED','UNCERTAIN','ABANDONED')),
 owner jsonb not null check(jsonb_typeof(owner)='object'),
 started_at timestamptz not null default now(),
 finished_at timestamptz,
 result jsonb,
 recovery_note text,
 check ((state='RUNNING')=(finished_at is null))
);
create unique index worker_executions_one_active on startup_radar.worker_executions ((true)) where finished_at is null;
create index worker_executions_job_idx on startup_radar.worker_executions(job_id) where job_id is not null;
alter table startup_radar.worker_executions enable row level security;
revoke all on startup_radar.worker_executions from public,anon,authenticated;
grant select,insert,update on startup_radar.worker_executions to service_role;
comment on table startup_radar.worker_executions is 'Privileged batch ledger. Active ownership never expires; recovery requires verified process termination.';
