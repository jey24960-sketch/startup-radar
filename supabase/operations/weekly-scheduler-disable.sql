-- NOT a migration. Separately approved rollback/pause of automatic dispatch.
-- Does not cancel an existing worker, modify a briefing or resend Telegram.
\set ON_ERROR_STOP on
\if :{?note}
\else
 \echo 'A reviewed rollback note is required'
 \quit 1
\endif
begin;
select startup_radar.configure_weekly_scheduler(false,null,:'note');
do $$
declare id bigint;
begin
 if to_regclass('cron.job') is not null then
  for id in select jobid from cron.job where jobname='startup-radar-weekly-dispatch'
   and database=current_database() and username=current_user
   and command='select startup_radar.weekly_scheduler_tick();'
  loop perform cron.unschedule(id); end loop;
 end if;
end $$;
commit;
-- Afterwards set RADAR_WEEKLY_SCHEDULER=github in GitHub to restore the legacy
-- next schedule. Existing dispatches remain correlated and idempotent.
