begin;
set local lock_timeout='3s';
set local statement_timeout='30s';

-- Read-only, additive weekly operations projection. Owned by startup-radar.
-- Existing collection/visibility/audit/withdrawal rules and all stored data stay unchanged.
-- Only server-observed facts are returned: no chat IDs, payloads, raw errors or worker owners.
create function public.gfc_radar_admin_weekly_status() returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare
 current_week date := date_trunc('week',now() at time zone 'Asia/Seoul')::date;
 due_at timestamptz;
 execution jsonb;
 collection jsonb;
 briefing jsonb;
 announcement jsonb;
 control jsonb;
begin
 perform startup_radar.require_admin();
 due_at := (current_week + interval '1 day 15 hours') at time zone 'Asia/Seoul';
 control := startup_radar.admin_control_snapshot();
 select jsonb_build_object('id',e.id,'state',e.state,'started_at',e.started_at,'finished_at',e.finished_at)
 into execution from startup_radar.worker_executions e
 where e.kind='WEEKLY' and e.started_at >= (current_week::timestamp at time zone 'Asia/Seoul')
 and e.started_at < ((current_week+7)::timestamp at time zone 'Asia/Seoul')
 order by e.started_at desc,e.id desc limit 1;
 select jsonb_build_object('id',r.id,'state',r.status,'started_at',r.started_at,'finished_at',r.finished_at,
  'bounded_completed',exists(select 1 from startup_radar.worker_executions e
   where e.kind='WEEKLY' and e.result->>'ingestion_run_id'=r.id::text
   and e.result->>'coverage_warning'='BOUNDED_WEEKLY_SCOPE'))
 into collection from startup_radar.ingestion_runs r
 where r.trigger_type='weekly' and r.started_at >= (current_week::timestamp at time zone 'Asia/Seoul')
 and r.started_at < ((current_week+7)::timestamp at time zone 'Asia/Seoul')
 order by r.started_at desc,r.id desc limit 1;
 select jsonb_build_object('id',b.id,'state',b.status,'title',b.title,'published_at',b.published_at,
  'withdrawn_at',b.withdrawn_at,'item_count',b.item_count,'revision',b.revision)
 into briefing from startup_radar.weekly_briefings b
 where b.week_start=current_week and b.publication_kind='WEEKLY';
 select jsonb_build_object('state',a.state,'created_at',a.created_at,'attempted_at',a.attempted_at,'delivered_at',a.delivered_at)
 into announcement from startup_radar.weekly_announcements a
 where a.briefing_id=(briefing->>'id')::uuid and a.target_kind='OFFICIAL_CHANNEL'
 order by a.created_at desc,a.id desc limit 1;
 return jsonb_build_object('as_of',now(),'week_start',current_week,'scheduled_at',due_at,
  'next_scheduled_at',case when now()<due_at then due_at else due_at+interval '7 days' end,
  'schedule',jsonb_build_object('timezone','Asia/Seoul','execution_gate','UNKNOWN','delivery_gate','UNKNOWN'),
  'operation',control->'operation','visibility',control->'visibility','telegram',control->'telegram',
  'execution',execution,'collection',collection,'briefing',briefing,'announcement',announcement);
end $$;
revoke all on function public.gfc_radar_admin_weekly_status() from public,anon,authenticated;
grant execute on function public.gfc_radar_admin_weekly_status() to authenticated,service_role;
comment on function public.gfc_radar_admin_weekly_status() is
 'Admin-only observed current Seoul-week facts. scheduled_at is the repository timetable, never proof the external scheduler or delivery gate is enabled.';
notify pgrst,'reload schema';
commit;
