-- Read-only metadata; never select Vault values, pg_net request headers/bodies,
-- Telegram target IDs or worker owner payloads.
begin read only;
select count(*) as active_workers from startup_radar.worker_executions where finished_at is null;
select count(*) as duplicate_weekly_publications from (
 select week_start from startup_radar.weekly_briefings where publication_kind='WEEKLY'
 group by week_start having count(*)>1
) duplicates;
select extname,extversion from pg_extension where extname in ('pg_cron','pg_net','supabase_vault');
select name,default_version from pg_available_extensions where name in ('pg_cron','pg_net','supabase_vault');
select to_regprocedure('public.gfc_radar_admin_weekly_status()') is not null as prerequisite_admin_snapshot,
 to_regclass('startup_radar.weekly_schedule_requests') is not null as coordinator_already_present;
select version,name from supabase_migrations.schema_migrations order by version desc limit 5;
commit;
