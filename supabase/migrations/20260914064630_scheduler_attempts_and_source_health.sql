begin;
set local lock_timeout='3s';
set local statement_timeout='30s';

create table startup_radar.schedule_task_attempts (
 id uuid primary key default gen_random_uuid(),
 task_key text not null references startup_radar.schedule_claims,
 attempt_number integer not null check(attempt_number>0),
 kind text not null,
 state text not null check(state in ('PENDING','RUNNING','SUCCESS','PARTIAL_SUCCESS','FAILED_RETRYABLE','FAILED_TERMINAL','UNCERTAIN')),
 execution_id uuid references startup_radar.worker_executions,
 previous_attempt_id uuid references startup_radar.schedule_task_attempts,
 reason_code text,
 next_retry_at timestamptz,
 result jsonb,
 origin text not null default 'SCHEDULED' check(origin in ('SCHEDULED','AUTO_RETRY','OPERATOR_RETRY','LEGACY_SNAPSHOT')),
 recovery_note text,
 created_at timestamptz not null default now(),
 started_at timestamptz,
 finished_at timestamptz,
 unique(task_key,attempt_number)
);
create unique index schedule_one_running_attempt on startup_radar.schedule_task_attempts(task_key) where state='RUNNING';
create index schedule_attempt_execution_idx on startup_radar.schedule_task_attempts(execution_id);
create index schedule_attempt_previous_idx on startup_radar.schedule_task_attempts(previous_attempt_id);
create index schedule_attempt_retry_idx on startup_radar.schedule_task_attempts(next_retry_at) where state='FAILED_RETRYABLE';
alter table startup_radar.schedule_task_attempts enable row level security;
revoke all on startup_radar.schedule_task_attempts from public,anon,authenticated;
grant all on startup_radar.schedule_task_attempts to service_role;

-- Snapshot legacy failures before a later attempt can update the claim summary.
-- Missing legacy root-cause metadata never grants automatic retry permission.
insert into startup_radar.schedule_task_attempts(task_key,attempt_number,kind,state,reason_code,result,origin,created_at,started_at,finished_at)
select task_key,1,kind,
 case when state='FAILED' then 'FAILED_TERMINAL'
      when state='SUCCESS' and result->>'ingestion_status'='PARTIAL_SUCCESS' then 'PARTIAL_SUCCESS'
      else state end,
 case when state='FAILED' then 'LEGACY_UNCLASSIFIED' else null end,
 result,'LEGACY_SNAPSHOT',created_at,created_at,finished_at
from startup_radar.schedule_claims;

insert into startup_radar.runtime_settings(key,value)
values('ingestion_retry_policy','{"max_attempts":3,"backoff_seconds":[900,3600],"max_age_hours":24}')
on conflict(key) do nothing;

alter table startup_radar.source_run_results add column coverage jsonb not null default '{}';
alter table startup_radar.sources
 add column last_successful_full_scan_at timestamptz,
 add column last_persisted_at timestamptz,
 add column last_source_observation_at timestamptz,
 add column last_failure_at timestamptz,
 add column last_failure_reason text;

-- Existing observations are evidence of persistence, not of a full scan.
update startup_radar.sources s set last_persisted_at=x.last_seen,last_source_observation_at=x.last_seen
from (select source_id,max(last_seen_at) last_seen from startup_radar.program_sources group by source_id) x
where s.id=x.source_id;

commit;
