begin;
set local lock_timeout='3s';
set local statement_timeout='30s';

create table startup_radar.extraction_attempts (
 id uuid primary key default gen_random_uuid(),
 input_hash text not null,
 attempt_number integer not null check(attempt_number>0),
 source_id uuid references startup_radar.sources on delete set null,
 state text not null check(state in ('RUNNING','SUCCESS','FAILED','UNCERTAIN')),
 owner_token uuid not null,
 owner_identity jsonb not null,
 lease_expires_at timestamptz not null,
 retryable boolean not null default false,
 operator_retry_allowed boolean not null default false,
 next_retry_at timestamptz,
 error_kind text,
 metadata jsonb not null default '{}',
 created_at timestamptz not null default now(),
 finished_at timestamptz,
 unique(input_hash,attempt_number)
);
create unique index extraction_attempt_running on startup_radar.extraction_attempts(input_hash) where state='RUNNING';
create index extraction_attempt_source on startup_radar.extraction_attempts(source_id);
alter table startup_radar.extraction_attempts enable row level security;
revoke all on startup_radar.extraction_attempts from public,anon,authenticated;
grant all on startup_radar.extraction_attempts to service_role;

create table startup_radar.program_quality (
 program_version_id uuid primary key references startup_radar.program_versions on delete cascade,
 state text not null check(state in ('ACTIONABLE','NEEDS_REVIEW','UNVERIFIABLE')),
 reasons text[] not null default '{}',
 metrics jsonb not null default '{}',
 policy_version text not null,
 assessed_at timestamptz not null default now(),
 check(state='ACTIONABLE' or cardinality(reasons)>0)
);
alter table startup_radar.program_quality enable row level security;
revoke all on startup_radar.program_quality from public,anon,authenticated;
grant all on startup_radar.program_quality to service_role;
grant select on startup_radar.program_quality to authenticated;
create policy member_quality_read on startup_radar.program_quality for select to authenticated using (
 (select public.my_role()) in ('member','admin')
);

-- Explicitly unassessed until the controlled stored-evidence refresh runs.
insert into startup_radar.program_quality(program_version_id,state,reasons,policy_version)
 select v.id,case when v.evidence_complete then 'NEEDS_REVIEW' else 'UNVERIFIABLE' end,
 array['OTHER_REVIEW_REQUIRED'],'unassessed'
 from startup_radar.programs p join startup_radar.program_versions v on v.id=p.current_version_id;

commit;
