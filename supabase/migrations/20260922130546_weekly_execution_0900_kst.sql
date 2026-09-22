-- Approved calendar change only: Tuesday 09:00 KST = Tuesday 00:00 UTC.
-- Keep the same private function, owner, privileges, controls and response keys.
-- No collection, publication, delivery, scheduler activation or data rewrite.
begin;
set local lock_timeout='3s';
set local statement_timeout='30s';
create or replace function startup_radar.admin_control_snapshot() returns jsonb
language sql stable security definer set search_path='' as $$
 with op as (select value from startup_radar.runtime_settings where key='radar_operation'),
  vis as (select value from startup_radar.runtime_settings where key='radar_visibility'),
  tg as (select value from startup_radar.runtime_settings where key='weekly_telegram_channel')
 select jsonb_build_object(
  'operation',jsonb_build_object('enabled',coalesce((select (value->>'enabled')::boolean from op),true),
   'reason',(select value->>'reason' from op),'updated_at',(select value->>'updated_at' from op),
   'updated_by',(select value->>'updated_by' from op),'version',coalesce((select (value->>'version')::integer from op),1)),
  'visibility',jsonb_build_object('mode',startup_radar.visibility_mode(),
   'reason',(select value->>'reason' from vis),'updated_at',(select value->>'updated_at' from vis),
   'updated_by',(select value->>'updated_by' from vis),'version',coalesce((select (value->>'version')::integer from vis),1)),
  'telegram',jsonb_build_object(
   'configured',coalesce((select nullif(btrim(value->>'chat_id'),'') is not null from tg),false),
   'enabled',coalesce((select (value->>'enabled')::boolean from tg),false),
   'name',coalesce((select nullif(value->>'name','') from tg),'GFC StartupRadar'),
   'join_url',(select nullif(btrim(value->>'join_url'),'') from tg),
   'broadcast_available',coalesce((select (value->>'enabled')::boolean and nullif(btrim(value->>'chat_id'),'') is not null from tg),false)
    and startup_radar.visibility_mode()<>'PRIVATE' and coalesce((select (value->>'enabled')::boolean from op),true)),
  'schedule_gate',jsonb_build_object('name','RADAR_V2_ENABLED','source','github_actions_variable','readable',false,'mutable_from_web',false,
   'schedule','Tuesday 09:00 Asia/Seoul (cron 0 0 * * 2)'),
  'as_of',now());
$$;
notify pgrst,'reload schema';
commit;
