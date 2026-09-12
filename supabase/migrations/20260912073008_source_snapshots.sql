-- Immutable source observations used by a specific canonical program version.
create table radar.program_source_snapshots (
 id uuid primary key default gen_random_uuid(),
 program_id uuid not null references radar.programs,
 program_version_id uuid not null,
 source_id uuid not null references radar.sources,
 source_program_id text, discovery_url text not null, official_detail_url text not null,
 raw_metadata jsonb not null, source_config jsonb not null,
 detail_hash text not null, observation_hash text not null,
 extraction_metadata jsonb not null default '{}',
 observed_at timestamptz not null default now(),
 foreign key(program_version_id,program_id) references radar.program_versions(id,program_id),
 unique(program_version_id,source_id,observation_hash)
);
create index source_snapshots_version_idx on radar.program_source_snapshots(program_version_id);
create index source_snapshots_source_idx on radar.program_source_snapshots(source_id,observed_at desc);
alter table radar.program_source_snapshots enable row level security;
grant select,insert on radar.program_source_snapshots to service_role;
grant select on radar.program_source_snapshots to authenticated;
create policy read_source_snapshots on radar.program_source_snapshots for select to authenticated
 using(exists(select 1 from radar.admin_users a where a.user_id=(select auth.uid())));
