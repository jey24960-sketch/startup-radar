begin;
set local lock_timeout='3s';
set local statement_timeout='30s';
-- Private projections are necessary because channel identifiers, source config
-- and raw run errors must not become member-readable table columns.
create function startup_radar.member_preferences(p_team_id uuid,p_changes jsonb default null)
returns jsonb language plpgsql volatile security definer set search_path='' as $$
declare actor uuid=auth.uid(); membership_role text; preferences jsonb; channels jsonb; k text; v jsonb;
begin
 if actor is null or coalesce(public.my_role(),'') not in ('member','admin') then raise exception using errcode='42501',message='Verified GFC membership required'; end if;
 select m.role into membership_role from startup_radar.team_members m where m.team_id=p_team_id and m.user_id=actor for share;
 if membership_role is null then raise exception using errcode='42501',message='Team is not accessible'; end if;
 if p_changes is not null then
  if membership_role not in ('OWNER','EDITOR') then raise exception using errcode='42501',message='Team editing requires owner/editor membership'; end if;
  if jsonb_typeof(p_changes)<>'object' or not (p_changes ?& array['enabled','digest_enabled','alerts_enabled','reminders_enabled']) then
   raise exception using errcode='22023',message='All notification flags are required'; end if;
  for k,v in select * from jsonb_each(p_changes) loop
   if k not in ('enabled','digest_enabled','alerts_enabled','reminders_enabled') or jsonb_typeof(v)<>'boolean' then
    raise exception using errcode='22023',message='Invalid notification preference'; end if;
  end loop;
  insert into startup_radar.team_notification_preferences(team_id,enabled,digest_enabled,alerts_enabled,reminders_enabled)
   values(p_team_id,(p_changes->>'enabled')::boolean,(p_changes->>'digest_enabled')::boolean,(p_changes->>'alerts_enabled')::boolean,(p_changes->>'reminders_enabled')::boolean)
   on conflict(team_id) do update set enabled=excluded.enabled,digest_enabled=excluded.digest_enabled,alerts_enabled=excluded.alerts_enabled,reminders_enabled=excluded.reminders_enabled;
  update startup_radar.telegram_subscriptions set enabled=(p_changes->>'enabled')::boolean,digest_enabled=(p_changes->>'digest_enabled')::boolean,
   alerts_enabled=(p_changes->>'alerts_enabled')::boolean,reminders_enabled=(p_changes->>'reminders_enabled')::boolean where team_id=p_team_id;
  insert into startup_radar.admin_audit(actor_id,action,entity_id,detail) values(actor,'TEAM_NOTIFICATION_PREFERENCES',p_team_id::text,p_changes);
 end if;
 select jsonb_build_object('enabled',p.enabled,'digest_enabled',p.digest_enabled,'alerts_enabled',p.alerts_enabled,'reminders_enabled',p.reminders_enabled)
  into preferences from startup_radar.team_notification_preferences p where p.team_id=p_team_id;
 select coalesce(jsonb_agg(jsonb_build_object('enabled',s.enabled,'digest_enabled',s.digest_enabled,'alerts_enabled',s.alerts_enabled,'reminders_enabled',s.reminders_enabled) order by s.created_at,s.id),'[]')
  into channels from startup_radar.telegram_subscriptions s where s.team_id=p_team_id;
 preferences=coalesce(preferences,channels->0,'{"enabled":true,"digest_enabled":true,"alerts_enabled":true,"reminders_enabled":true}');
 return jsonb_build_object('connected',jsonb_array_length(channels)>0,'preferences',preferences,'subscriptions',channels,'updated',case when p_changes is not null then jsonb_array_length(channels) else null end);
end $$;
create function public.gfc_radar_preferences(p_team_id uuid)
returns jsonb language sql volatile security invoker set search_path='' as $$ select startup_radar.member_preferences(p_team_id); $$;
create function public.gfc_radar_save_preferences(p_team_id uuid,p_preferences jsonb)
returns jsonb language plpgsql volatile security invoker set search_path='' as $$
begin
 if p_preferences is null then raise exception using errcode='22023',message='Preferences are required'; end if;
 return startup_radar.member_preferences(p_team_id,p_preferences);
end $$;

create function startup_radar.admin_health()
returns jsonb language plpgsql stable security definer set search_path='' as $$
declare sources jsonb; runs jsonb; queue jsonb; computation jsonb; scheduling jsonb; active_count integer; success_count integer;
begin
 if auth.uid() is null or coalesce(public.my_role(),'')<>'admin' then raise exception using errcode='42501',message='GFC admin required'; end if;
 select coalesce(jsonb_agg(jsonb_build_object('id',s.id,'slug',s.slug,'name',s.name,'adapter',s.adapter,'enabled',s.enabled,
  'last_attempted_at',s.last_attempted_at,'last_successful_at',s.last_successful_at,'status',r.status,
  'discovered_count',r.discovered_count,'fetched_count',r.fetched_count,'parsed_count',r.parsed_count,'latency_ms',r.latency_ms,
  'failures',coalesce((select jsonb_agg(jsonb_build_object('kind',case when f->>'kind' ~ '^[A-Z_]{1,64}$' then f->>'kind' else 'SOURCE_ERROR' end))
   from jsonb_array_elements(case when jsonb_typeof(r.failures)='array' then r.failures else '[]' end) f),'[]')) order by s.slug),'[]'),
  count(*) filter(where s.enabled),count(*) filter(where s.enabled and r.status='SUCCESS')
  into sources,active_count,success_count from startup_radar.sources s left join lateral (
   select r.* from startup_radar.source_run_results r where r.source_id=s.id order by r.created_at desc,r.id desc limit 1
  ) r on true;
 select coalesce(jsonb_agg(jsonb_build_object('id',r.id,'status',r.status,'started_at',r.started_at,'finished_at',r.finished_at,
  'summary',jsonb_build_object('new_programs',case when jsonb_typeof(r.summary->'new_programs')='number' then r.summary->'new_programs' end,
    'eligibility_failed',r.summary->>'eligibility_error' is not null)) order by r.started_at desc),'[]') into runs
  from (select * from startup_radar.ingestion_runs order by started_at desc,id desc limit 20) r;
 select jsonb_build_object('pending',count(*) filter(where state='PENDING'),'running',count(*) filter(where state='RUNNING'),
  'failed',count(*) filter(where state='FAILED'),'oldest_pending_at',min(requested_at) filter(where state='PENDING')) into queue
  from startup_radar.profile_calculation_requests;
 select jsonb_build_object('state',state,'started_at',started_at,'finished_at',finished_at,'has_error',error_kind is not null) into computation
  from startup_radar.member_read_state where singleton;
 select jsonb_build_object('enabled',value->'enabled'='true'::jsonb,'ingestion_enabled',value->'ingestion_enabled'='true'::jsonb) into scheduling
  from startup_radar.runtime_settings where key='scheduling';
 return jsonb_build_object('sources',sources,'runs',runs,'tracked_sources',jsonb_array_length(sources),'enabled_sources',active_count,
  'successful_sources',success_count,'tracked_source_success_rate',case when active_count>0 then round(100.0*success_count/active_count,1) end,
  'failure_counts',jsonb_build_object('documents',(select count(*) from startup_radar.documents where extraction_status in ('FAILED','UNSUPPORTED')),
   'eligibility',(select count(*) from startup_radar.ingestion_runs where summary->>'eligibility_error' is not null)),
  'calculation_queue',queue,'calculation',computation,'scheduling',scheduling,
  'coverage_note','등록된 활성 소스의 최근 수집 성공률이며 국내 전체 창업지원사업의 포괄률이 아닙니다.');
end $$;
create function public.gfc_radar_health()
returns jsonb language sql stable security invoker set search_path='' as $$ select startup_radar.admin_health(); $$;
revoke all on function startup_radar.member_preferences(uuid,jsonb),startup_radar.admin_health(),
 public.gfc_radar_preferences(uuid),public.gfc_radar_save_preferences(uuid,jsonb),public.gfc_radar_health() from public,anon,authenticated,service_role;
grant execute on function startup_radar.member_preferences(uuid,jsonb),startup_radar.admin_health(),
 public.gfc_radar_preferences(uuid),public.gfc_radar_save_preferences(uuid,jsonb),public.gfc_radar_health() to authenticated;
notify pgrst,'reload schema';
commit;
