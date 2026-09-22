-- NOT a migration; privileged, separately approved activation only.
-- psql --set active_from_week=YYYY-MM-DD --set note='approved cutover reference'
--       --file supabase/operations/weekly-scheduler-activate.sql
-- Provision the repository-scoped Actions-write credential through Supabase
-- Vault beforehand, named startup_radar_github_dispatch. Never put it here.
-- First deploy the compatible worker/workflow and set GitHub
-- RADAR_WEEKLY_SCHEDULER=supabase, RADAR_V2_ENABLED=true.
\set ON_ERROR_STOP on
\if :{?active_from_week}
\else
 \echo 'active_from_week (future Seoul Monday) is required'
 \quit 1
\endif
\if :{?note}
\else
 \echo 'A reviewed cutover note is required'
 \quit 1
\endif
begin;
set local lock_timeout='3s';
set local statement_timeout='30s';
create extension if not exists pg_cron;
create extension if not exists pg_net;
-- Queued pg_net headers contain the credential; never expose them to clients.
revoke all on schema net from public,anon,authenticated;
revoke all on net.http_request_queue,net._http_response from public,anon,authenticated,service_role;
do $$
begin
 if not exists(select 1 from vault.secrets where name='startup_radar_github_dispatch') then
  raise exception 'Provision the approved Vault credential first';
 end if;
 if exists(select 1 from cron.job where jobname='startup-radar-weekly-dispatch'
     and (database<>current_database() or username<>current_user
       or command<>'select startup_radar.weekly_scheduler_tick();')) then
  raise exception 'Existing cron name belongs to another target; review before changing it';
 end if;
end $$;
select cron.schedule('startup-radar-weekly-dispatch','*/5 * * * *','select startup_radar.weekly_scheduler_tick();');
select startup_radar.configure_weekly_scheduler(true,:'active_from_week'::date,:'note');
commit;
-- No dispatch is performed here. No previous week is backfilled.
