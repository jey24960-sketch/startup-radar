begin;
set local lock_timeout='3s';
set local statement_timeout='30s';

-- Answers describe one team's declaration for one immutable notice version.
-- Do not add these program-specific promises to the global GFC/team profile.
create table startup_radar.team_program_responses (
 team_id uuid not null references startup_radar.teams on delete cascade,
 program_version_id uuid not null references startup_radar.program_versions on delete cascade,
 responses jsonb not null default '{}' check(jsonb_typeof(responses)='object' and octet_length(responses::text)<=20000),
 revision integer not null default 1 check(revision>0),
 updated_by uuid not null references auth.users,
 updated_at timestamptz not null default now(),
 primary key(team_id,program_version_id)
);
create index program_responses_version_idx on startup_radar.team_program_responses(program_version_id);
create index program_responses_actor_idx on startup_radar.team_program_responses(updated_by);
alter table startup_radar.team_program_responses enable row level security;
revoke all on startup_radar.team_program_responses from public,anon,authenticated,service_role;
grant select on startup_radar.team_program_responses to authenticated;
grant select,insert,update on startup_radar.team_program_responses to service_role;
create policy read_program_responses on startup_radar.team_program_responses for select to authenticated using (
 (select public.my_role()) in ('member','admin') and team_id in
 (select m.team_id from startup_radar.team_members m where m.user_id=(select auth.uid())));

-- Complete source-review decisions remain worker-only; no client approval path.
create table startup_radar.program_reviews (
 id uuid primary key default gen_random_uuid(),
 input_hash text not null check(input_hash ~ '^[0-9a-f]{64}$'),
 source_id uuid not null references startup_radar.sources,
 program_id uuid not null references startup_radar.programs,
 base_version_id uuid not null references startup_radar.program_versions,
 decision jsonb not null check(jsonb_typeof(decision)='object' and octet_length(decision::text)<=1000000),
 reviewer_kind text not null check(reviewer_kind in ('AGENT_VISUAL_REVIEW','OPERATOR_REVIEW')),
 reviewer_label text not null check(length(reviewer_label) between 1 and 200),
 created_at timestamptz not null default now(),
 revoked_at timestamptz
);
create index program_reviews_input_idx on startup_radar.program_reviews(input_hash,created_at desc,id desc);
create index program_reviews_source_idx on startup_radar.program_reviews(source_id);
create index program_reviews_program_idx on startup_radar.program_reviews(program_id);
create index program_reviews_version_idx on startup_radar.program_reviews(base_version_id);
alter table startup_radar.program_reviews enable row level security;
revoke all on startup_radar.program_reviews from public,anon,authenticated,service_role;
grant select,insert on startup_radar.program_reviews to service_role;
grant update(revoked_at) on startup_radar.program_reviews to service_role;

alter table startup_radar.member_program_results add column response_snapshot jsonb not null default '{}';

-- The definer is needed only to atomically write the protected answer, audit and
-- existing calculation outbox without giving clients direct UPDATE privileges.
create function startup_radar.write_program_responses(p_team_id uuid,p_version_id uuid,p_responses jsonb,p_expected_revision integer)
returns jsonb language plpgsql volatile security definer set search_path='' as $$
declare actor uuid=auth.uid(); membership_role text; prior startup_radar.team_program_responses;
 current_version uuid; facts jsonb; k text; v jsonb; clean jsonb; next_revision integer; profile_revision integer;
begin
 if actor is null or coalesce(public.my_role(),'') not in ('member','admin') then
  raise exception using errcode='42501',message='Verified GFC membership required'; end if;
 select m.role into membership_role from startup_radar.team_members m where m.team_id=p_team_id and m.user_id=actor for share;
 if membership_role is null or membership_role not in ('OWNER','EDITOR') then
  raise exception using errcode='42501',message='Team editing requires owner/editor membership'; end if;
 -- A single team row serializes first inserts as well as updates.
 select version into profile_revision from startup_radar.team_profiles where team_id=p_team_id for update;
 if not found then raise exception using errcode='42501',message='Team is not accessible'; end if;
 select p.current_version_id,v.normalized into current_version,facts from startup_radar.program_versions v
  join startup_radar.programs p on p.id=v.program_id where v.id=p_version_id for share of p;
 if current_version is null or current_version<>p_version_id then
  raise exception using errcode='40001',message='Only the current notice version accepts answers'; end if;
 if p_responses is null or jsonb_typeof(p_responses)<>'object' or octet_length(p_responses::text)>20000
  or p_expected_revision is null or p_expected_revision<0 then
  raise exception using errcode='22023',message='Invalid program responses'; end if;
 for k,v in select * from jsonb_each(p_responses) loop
  if jsonb_typeof(v) not in ('boolean','null') or not exists (
   select 1 from jsonb_array_elements(facts->'requirements') r
   where r->>'key'='program_response' and r->>'response_id'=k and r->>'operator'='EQ'
    and jsonb_typeof(r->'value')='boolean' and r->>'certain'='true') then
   raise exception using errcode='22023',message='Unknown question or invalid response value'; end if;
 end loop;
 clean=jsonb_strip_nulls(p_responses);
 select * into prior from startup_radar.team_program_responses where team_id=p_team_id and program_version_id=p_version_id;
 if prior.team_id is not null and prior.responses=clean then
  return jsonb_build_object('responses',prior.responses,'revision',prior.revision,'changed',false); end if;
 if coalesce(prior.revision,0)<>p_expected_revision then
  raise exception using errcode='40001',message='Responses changed; refresh before editing'; end if;
 next_revision=coalesce(prior.revision,0)+1;
 insert into startup_radar.team_program_responses(team_id,program_version_id,responses,revision,updated_by)
  values(p_team_id,p_version_id,clean,next_revision,actor)
  on conflict(team_id,program_version_id) do update set responses=excluded.responses,revision=excluded.revision,updated_by=actor,updated_at=now();
 insert into startup_radar.profile_calculation_requests(team_id,profile_version) values(p_team_id,profile_revision)
  on conflict(team_id,profile_version) do update set state='PENDING',requested_at=now(),started_at=null,finished_at=null,error_kind=null;
 insert into startup_radar.admin_audit(actor_id,action,entity_id,detail)
  values(actor,'PROGRAM_RESPONSES',p_team_id::text,jsonb_build_object('program_version_id',p_version_id,'revision',next_revision));
 return jsonb_build_object('responses',clean,'revision',next_revision,'changed',true);
end $$;
create function public.gfc_radar_program_responses(p_team_id uuid,p_version_id uuid,p_responses jsonb,p_expected_revision integer)
returns jsonb language sql volatile security invoker set search_path='' as $$
 select startup_radar.write_program_responses(p_team_id,p_version_id,p_responses,p_expected_revision);
$$;
revoke all on function startup_radar.write_program_responses(uuid,uuid,jsonb,integer),public.gfc_radar_program_responses(uuid,uuid,jsonb,integer)
 from public,anon,authenticated,service_role;
grant execute on function startup_radar.write_program_responses(uuid,uuid,jsonb,integer),public.gfc_radar_program_responses(uuid,uuid,jsonb,integer) to authenticated;

create or replace function startup_radar.member_program_item(p_version_id uuid,p_scope jsonb)
returns jsonb language plpgsql stable security invoker set search_path='' as $$
declare v startup_radar.program_versions; r startup_radar.member_program_results;
 live_status text; end_at timestamptz; start_at timestamptz; config startup_radar.member_read_state;
 answers jsonb='{}'; answer_revision integer=0;
begin
 select * into v from startup_radar.program_versions where id=p_version_id;
 if not found then raise exception using errcode='P0002',message='Program/version not found'; end if;
 if p_scope->>'key' not like 'preset:%' then
  select x.responses,x.revision into answers,answer_revision from startup_radar.team_program_responses x
   where x.team_id=(p_scope->>'key')::uuid and x.program_version_id=p_version_id;
 end if;
 answers=coalesce(answers,'{}'); answer_revision=coalesce(answer_revision,0);
 select * into config from startup_radar.member_read_state where singleton;
 select * into r from startup_radar.member_program_results x where x.program_version_id=v.id
   and x.scope_key=p_scope->>'key' and x.generation=config.generation
   and x.evaluated_on=(now() at time zone 'Asia/Seoul')::date and x.response_snapshot=answers
   and (x.team_id is null or (x.profile_version=(p_scope->>'version')::integer and x.profile_snapshot=p_scope->'profile'));
 end_at=(v.normalized->>'application_end_at')::timestamptz;
 start_at=(v.normalized->>'application_start_at')::timestamptz;
 live_status=case when end_at<now() then 'CLOSED' when start_at>now() then 'UPCOMING'
   when v.normalized->>'deadline_type' in ('ROLLING','UNTIL_BUDGET_EXHAUSTED') or end_at is not null then 'OPEN' else 'UNKNOWN' end;
 return jsonb_build_object('id',v.program_id,'version_id',v.id,'version',v.version,'facts',v.normalized,
  'updated_at',v.created_at,'status',live_status,
  'program_responses',jsonb_build_object('responses',answers,'revision',answer_revision),
  'days_left',(end_at at time zone 'Asia/Seoul')::date-(now() at time zone 'Asia/Seoul')::date,
  'calculation_state',case when r.program_version_id is not null then 'READY' when config.state='FAILED' then 'FAILED' else 'PENDING' end,
  'eligibility',r.eligibility,'recommendation',case when live_status in ('OPEN','UPCOMING') then r.recommendation else null end,
  'computed_at',r.computed_at);
end $$;

create or replace function public.gfc_radar_program_detail(p_program_id uuid,p_team_id uuid default null,p_preset integer default null,p_version_id uuid default null)
returns jsonb language plpgsql stable security invoker set search_path='' as $$
declare scope jsonb; version_id uuid; response jsonb;
begin
 scope=startup_radar.member_scope(p_team_id,p_preset);
 select v.id into version_id from startup_radar.programs p join startup_radar.program_versions v
  on v.program_id=p.id and v.id=coalesce(p_version_id,p.current_version_id) where p.id=p_program_id;
 if version_id is null then raise exception using errcode='P0002',message='Program/version not found'; end if;
 response=startup_radar.member_program_item(version_id,scope);
 return response || jsonb_build_object(
  'source_review',startup_radar.member_source_review(version_id),
  'versions',coalesce((select jsonb_agg(jsonb_build_object('id',id,'version',version,'created_at',created_at) order by version desc)
    from startup_radar.program_versions where program_id=p_program_id),'[]'::jsonb),
  'documents',coalesce((select jsonb_agg(jsonb_build_object('id',id,'original_url',original_url,'filename',filename,'detected_mime',detected_mime,
    'content_hash',content_hash,'fetch_status',fetch_status,'extraction_status',extraction_status,'error_kind',error_kind,'fetched_at',fetched_at) order by id)
    from startup_radar.documents where program_version_id=version_id),'[]'::jsonb),
  'changes',coalesce((select jsonb_agg(jsonb_build_object('event_type',event_type,'changed_fields',changed_fields,'created_at',created_at) order by created_at desc)
    from startup_radar.program_change_events where program_id=p_program_id),'[]'::jsonb));
end $$;

notify pgrst,'reload schema';
commit;
