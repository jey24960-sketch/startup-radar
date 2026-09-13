begin;
set local lock_timeout='3s';
set local statement_timeout='30s';

-- Batch-owned presentation results; existing canonical/trace tables stay intact.
create table startup_radar.member_read_state (
 singleton boolean primary key default true check(singleton),
 generation text not null,
 state text not null check(state in ('PENDING','RUNNING','SUCCESS','FAILED')),
 started_at timestamptz, finished_at timestamptz, error_kind text
);
insert into startup_radar.member_read_state values(true,'UNINITIALIZED','PENDING',null,null,null);
create table startup_radar.member_program_results (
 scope_key text not null,
 program_version_id uuid not null references startup_radar.program_versions on delete cascade,
 team_id uuid references startup_radar.teams on delete cascade,
 preset integer check(preset between 0 and 4),
 profile_version integer,
 profile_snapshot jsonb not null,
 evaluated_on date not null,
 generation text not null,
 eligibility jsonb not null,
 recommendation jsonb,
 computed_at timestamptz not null default now(),
 primary key(scope_key,program_version_id),
 check((team_id is null and preset is not null and profile_version is null and scope_key='preset:'||preset::text)
    or (team_id is not null and preset is null and profile_version is not null and profile_version>0 and scope_key=team_id::text))
);
create index member_results_version_idx on startup_radar.member_program_results(program_version_id);
create index member_results_team_idx on startup_radar.member_program_results(team_id);
alter table startup_radar.member_read_state enable row level security;
alter table startup_radar.member_program_results enable row level security;
revoke all on startup_radar.member_read_state,startup_radar.member_program_results from public,anon,authenticated;
grant select on startup_radar.member_read_state,startup_radar.member_program_results to authenticated;
grant all on startup_radar.member_read_state,startup_radar.member_program_results to service_role;
create policy member_read_state_select on startup_radar.member_read_state for select to authenticated
 using ((select public.my_role()) in ('member','admin'));
create policy member_results_select on startup_radar.member_program_results for select to authenticated
 using ((select public.my_role()) in ('member','admin') and (team_id is null or team_id in
   (select m.team_id from startup_radar.team_members m where m.user_id=(select auth.uid()))));

create function startup_radar.member_scope(p_team_id uuid,p_preset integer)
returns jsonb language plpgsql stable security invoker set search_path='' as $$
declare context jsonb; selected jsonb;
begin
 context=public.gfc_radar_me();
 if p_team_id is not null then
  if p_preset is not null then raise exception using errcode='22023',message='Choose team or preset'; end if;
  select t into selected from jsonb_array_elements(context->'teams') t where t->>'id'=p_team_id::text;
  if selected is null then raise exception using errcode='42501',message='Team is not accessible'; end if;
  return jsonb_build_object('key',p_team_id::text,'profile',selected->'profile','version',selected->'version');
 end if;
 if coalesce(p_preset,0) not between 0 and 4 then raise exception using errcode='22023',message='Invalid preset'; end if;
 return jsonb_build_object('key','preset:'||coalesce(p_preset,0)::text,'preset',coalesce(p_preset,0));
end $$;

create function startup_radar.member_program_item(p_version_id uuid,p_scope jsonb)
returns jsonb language plpgsql stable security invoker set search_path='' as $$
declare v startup_radar.program_versions; r startup_radar.member_program_results;
 live_status text; end_at timestamptz; start_at timestamptz; config startup_radar.member_read_state;
begin
 select * into v from startup_radar.program_versions where id=p_version_id;
 if not found then raise exception using errcode='P0002',message='Program/version not found'; end if;
 select * into config from startup_radar.member_read_state where singleton;
 select * into r from startup_radar.member_program_results x where x.program_version_id=v.id
   and x.scope_key=p_scope->>'key' and x.generation=config.generation
   and x.evaluated_on=(now() at time zone 'Asia/Seoul')::date
   and (x.team_id is null or (x.profile_version=(p_scope->>'version')::integer and x.profile_snapshot=p_scope->'profile'));
 end_at=(v.normalized->>'application_end_at')::timestamptz;
 start_at=(v.normalized->>'application_start_at')::timestamptz;
 live_status=case when end_at<now() then 'CLOSED' when start_at>now() then 'UPCOMING'
   when v.normalized->>'deadline_type' in ('ROLLING','UNTIL_BUDGET_EXHAUSTED') or end_at is not null then 'OPEN' else 'UNKNOWN' end;
 return jsonb_build_object('id',v.program_id,'version_id',v.id,'version',v.version,'facts',v.normalized,
  'updated_at',v.created_at,'status',live_status,
  'days_left',(end_at at time zone 'Asia/Seoul')::date-(now() at time zone 'Asia/Seoul')::date,
  'calculation_state',case when r.program_version_id is not null then 'READY' when config.state='FAILED' then 'FAILED' else 'PENDING' end,
  'eligibility',r.eligibility,'recommendation',case when live_status in ('OPEN','UPCOMING') then r.recommendation else null end,
  'computed_at',r.computed_at);
end $$;

create function public.gfc_radar_programs(
 p_team_id uuid default null,p_preset integer default null,p_q text default '',p_program_type text default null,
 p_status text default null,p_eligibility text default null,p_history boolean default false,
 p_recommended boolean default false,p_limit integer default 30,p_offset integer default 0,
 p_date_from date default null,p_date_to date default null)
returns jsonb language plpgsql stable security invoker set search_path='' as $$
declare scope jsonb; response jsonb;
begin
 scope=startup_radar.member_scope(p_team_id,p_preset);
 if p_limit is null or p_limit not between 1 and 100 or p_offset is null or p_offset<0 or length(coalesce(p_q,''))>200 then
  raise exception using errcode='22023',message='Invalid pagination or query'; end if;
 if p_status is not null and p_status not in ('OPEN','UPCOMING','CLOSED','UNKNOWN') then raise exception using errcode='22023',message='Invalid status'; end if;
 if p_eligibility is not null and p_eligibility not in ('ELIGIBLE','NEEDS_INFO','INELIGIBLE','UNVERIFIABLE') then raise exception using errcode='22023',message='Invalid eligibility'; end if;
 with candidates as materialized (
  select p.id,p.updated_at,p.application_end_at,startup_radar.member_program_item(p.current_version_id,scope) item
  from startup_radar.programs p where p.current_version_id is not null
   and (coalesce(p_q,'')='' or p.title ilike '%'||p_q||'%' or p.organization ilike '%'||p_q||'%')
   and (p_program_type is null or p_program_type=any(p.program_types))
   and (p_date_from is null or p.application_end_at >= (p_date_from::timestamp at time zone 'Asia/Seoul'))
   and (p_date_to is null or p.application_end_at < ((p_date_to+1)::timestamp at time zone 'Asia/Seoul'))
 ), active as materialized (
  select * from candidates where (coalesce(p_history,false) or item->>'status'<>'CLOSED')
    and (p_status is null or item->>'status'=p_status)
 ), filtered as materialized (
  select * from active where (p_eligibility is null or item->'eligibility'->>'status'=p_eligibility)
   and (not coalesce(p_recommended,false) or (item->'recommendation' <> 'null'::jsonb and item->>'status' in ('OPEN','UPCOMING')))
 ), page as (
  select item,id,updated_at,case when p_recommended then (item->'recommendation'->>'score')::numeric end score
  from filtered order by score desc nulls last,updated_at desc,id limit p_limit offset p_offset
 ) select jsonb_build_object('items',coalesce((select jsonb_agg(item order by score desc nulls last,updated_at desc,id) from page),'[]'::jsonb),
   'total',(select count(*) from filtered),'pending_count',(select count(*) from active where item->>'calculation_state'='PENDING'),
   'failed_count',(select count(*) from active where item->>'calculation_state'='FAILED'),'offset',p_offset,'limit',p_limit)
 into response;
 return response;
end $$;

create function public.gfc_radar_program_detail(p_program_id uuid,p_team_id uuid default null,p_preset integer default null,p_version_id uuid default null)
returns jsonb language plpgsql stable security invoker set search_path='' as $$
declare scope jsonb; version_id uuid; response jsonb;
begin
 scope=startup_radar.member_scope(p_team_id,p_preset);
 select v.id into version_id from startup_radar.programs p join startup_radar.program_versions v
  on v.program_id=p.id and v.id=coalesce(p_version_id,p.current_version_id) where p.id=p_program_id;
 if version_id is null then raise exception using errcode='P0002',message='Program/version not found'; end if;
 response=startup_radar.member_program_item(version_id,scope);
 return response || jsonb_build_object(
  'versions',coalesce((select jsonb_agg(jsonb_build_object('id',id,'version',version,'created_at',created_at) order by version desc)
    from startup_radar.program_versions where program_id=p_program_id),'[]'::jsonb),
  'documents',coalesce((select jsonb_agg(jsonb_build_object('id',id,'original_url',original_url,'filename',filename,'detected_mime',detected_mime,
    'fetch_status',fetch_status,'extraction_status',extraction_status,'error_kind',error_kind,'fetched_at',fetched_at) order by id)
    from startup_radar.documents where program_version_id=version_id),'[]'::jsonb),
  'changes',coalesce((select jsonb_agg(jsonb_build_object('event_type',event_type,'changed_fields',changed_fields,'created_at',created_at) order by created_at desc)
    from startup_radar.program_change_events where program_id=p_program_id),'[]'::jsonb));
end $$;
revoke all on function startup_radar.member_scope(uuid,integer),startup_radar.member_program_item(uuid,jsonb),
 public.gfc_radar_programs(uuid,integer,text,text,text,text,boolean,boolean,integer,integer,date,date),
 public.gfc_radar_program_detail(uuid,uuid,integer,uuid) from public,anon,authenticated,service_role;
grant execute on function startup_radar.member_scope(uuid,integer),startup_radar.member_program_item(uuid,jsonb),
 public.gfc_radar_programs(uuid,integer,text,text,text,text,boolean,boolean,integer,integer,date,date),
 public.gfc_radar_program_detail(uuid,uuid,integer,uuid) to authenticated;
notify pgrst,'reload schema';
commit;
