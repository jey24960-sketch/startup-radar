begin;
set local lock_timeout='3s';
set local statement_timeout='30s';

-- Generated from tools/profile_contract.py; parity is verified against Python.
create function startup_radar.profile_contract() returns jsonb language sql immutable security invoker set search_path='' as $contract$
 select '{"defaults": {"age_band": null, "applicant_type": null, "assumed_fields": [], "business_age_months": null, "business_registration_date": null, "business_status": null, "business_status_options": null, "founder_age": null, "global_expansion_interest": null, "has_revenue": null, "industry": null, "investment_received": null, "investment_stage": null, "preferred_program_types": null, "preset": null, "prior_support_restrictions": null, "product_stage": null, "region": null, "revenue": null, "revenue_band": null, "student_status": null, "team_size": null, "team_status": null, "university_affiliation": null}, "fields": {"age_band": {"maxItems": 2, "minItems": 2, "nullable": true, "type": "array"}, "applicant_type": {"nullable": true, "type": "string"}, "assumed_fields": {"items": {"type": "string"}, "nullable": false, "type": "array"}, "business_age_months": {"minimum": 0, "nullable": true, "type": "integer"}, "business_registration_date": {"format": "date", "nullable": true, "type": "string"}, "business_status": {"enum": ["PRE_BUSINESS", "SOLE_PROPRIETOR", "CORPORATION"], "nullable": true, "type": "string"}, "business_status_options": {"items": {"enum": ["PRE_BUSINESS", "SOLE_PROPRIETOR", "CORPORATION"], "type": "string"}, "nullable": true, "type": "array"}, "founder_age": {"maximum": 120, "minimum": 0, "nullable": true, "type": "integer"}, "global_expansion_interest": {"nullable": true, "type": "boolean"}, "has_revenue": {"nullable": true, "type": "boolean"}, "industry": {"items": {"type": "string"}, "nullable": true, "type": "array"}, "investment_received": {"nullable": true, "type": "boolean"}, "investment_stage": {"nullable": true, "type": "string"}, "preferred_program_types": {"items": {"type": "string"}, "nullable": true, "type": "array"}, "preset": {"maximum": 4, "minimum": 0, "nullable": true, "type": "integer"}, "prior_support_restrictions": {"items": {"type": "string"}, "nullable": true, "type": "array"}, "product_stage": {"enum": ["IDEA", "LANDING", "MVP", "REVENUE"], "nullable": true, "type": "string"}, "region": {"nullable": true, "type": "string"}, "revenue": {"minimum": 0, "nullable": true, "type": "number"}, "revenue_band": {"nullable": true, "type": "string"}, "student_status": {"nullable": true, "type": "boolean"}, "team_size": {"maximum": 10000, "minimum": 1, "nullable": true, "type": "integer"}, "team_status": {"enum": ["PRE_TEAM", "FORMING", "TEAMED"], "nullable": true, "type": "string"}, "university_affiliation": {"nullable": true, "type": "string"}}, "presets": [{"business_status": "PRE_BUSINESS", "has_revenue": false, "product_stage": "IDEA", "team_status": "PRE_TEAM"}, {"business_status": "PRE_BUSINESS", "product_stage": "IDEA", "team_status": "TEAMED"}, {"business_status": "PRE_BUSINESS", "product_stage": "LANDING", "team_status": "TEAMED"}, {"product_stage": "MVP", "team_status": "TEAMED"}, {"business_status_options": ["SOLE_PROPRIETOR", "CORPORATION"]}]}'::jsonb;
$contract$;

create function startup_radar.validate_member_profile(p_profile jsonb)
returns jsonb language plpgsql immutable security invoker set search_path='' as $$
declare contract jsonb=startup_radar.profile_contract(); k text; v jsonb; spec jsonb; item jsonb; kind text;
begin
 if p_profile is null or jsonb_typeof(p_profile)<>'object' or octet_length(p_profile::text)>65536 then
  raise exception using errcode='22023',message='Invalid profile object'; end if;
 for k,v in select * from jsonb_each(p_profile) loop
  spec=contract->'fields'->k;
  if spec is null then raise exception using errcode='22023',message='Unsupported profile field'; end if;
  if v='null'::jsonb then
   if spec->>'nullable'='true' then continue; end if;
   raise exception using errcode='22023',message='Non-null profile field required';
  end if;
  kind=spec->>'type';
  if jsonb_typeof(v)<>(case when kind in ('integer','number') then 'number' else kind end) then
   raise exception using errcode='22023',message='Invalid profile value type'; end if;
  if kind in ('integer','number') then
   if (kind='integer' and (v::text)::numeric<>trunc((v::text)::numeric))
      or ((v::text)::numeric < (spec->>'minimum')::numeric) or ((v::text)::numeric > (spec->>'maximum')::numeric)
      or abs((v::text)::numeric)>1e308 then raise exception using errcode='22023',message='Invalid numeric range'; end if;
  end if;
  if spec ? 'enum' and not (spec->'enum' @> jsonb_build_array(v)) then raise exception using errcode='22023',message='Invalid profile option'; end if;
  if spec->>'format'='date' then
   if (v#>>'{}') !~ '^\d{4}-\d{2}-\d{2}$' then raise exception using errcode='22023',message='Invalid profile date'; end if;
   begin perform (v#>>'{}')::date; exception when datetime_field_overflow or invalid_datetime_format then
    raise exception using errcode='22023',message='Invalid profile date'; end;
  end if;
  if kind='array' then
   if jsonb_array_length(v)>100 or jsonb_array_length(v)<(spec->>'minItems')::integer or jsonb_array_length(v)>(spec->>'maxItems')::integer then
    raise exception using errcode='22023',message='Invalid profile array length'; end if;
   for item in select * from jsonb_array_elements(v) loop
    if spec ? 'items' and jsonb_typeof(item)<>spec->'items'->>'type' then raise exception using errcode='22023',message='Invalid profile array item'; end if;
    if spec->'items' ? 'enum' and not (spec->'items'->'enum' @> jsonb_build_array(item)) then raise exception using errcode='22023',message='Invalid profile array option'; end if;
    if k='assumed_fields' and (not (contract->'fields' ? (item#>>'{}')) or item#>>'{}' in ('assumed_fields','preset')) then raise exception using errcode='22023',message='Invalid assumed field'; end if;
   end loop;
  end if;
 end loop;
 if p_profile->'age_band' is distinct from 'null'::jsonb and p_profile ? 'age_band' then
  if exists(select 1 from jsonb_array_elements(p_profile->'age_band') a where jsonb_typeof(a)<>'number') then raise exception using errcode='22023',message='Invalid age band'; end if;
  if (p_profile->'age_band'->>0)::numeric<0 or (p_profile->'age_band'->>1)::numeric>120
     or (p_profile->'age_band'->>0)::numeric>(p_profile->'age_band'->>1)::numeric
     or (p_profile->'age_band'->>0)::numeric<>trunc((p_profile->'age_band'->>0)::numeric)
     or (p_profile->'age_band'->>1)::numeric<>trunc((p_profile->'age_band'->>1)::numeric) then raise exception using errcode='22023',message='Invalid age band'; end if;
 end if;
 if p_profile->>'business_status' is not null and jsonb_array_length(nullif(p_profile->'business_status_options','null'))>0
  and not (p_profile->'business_status_options' @> jsonb_build_array(p_profile->'business_status')) then
  raise exception using errcode='22023',message='Business status contradicts options'; end if;
 return contract->'defaults' || p_profile;
end $$;

create function startup_radar.apply_member_profile(p_profile jsonb,p_preset integer,p_changes jsonb)
returns jsonb language plpgsql immutable security invoker set search_path='' as $$
declare profile jsonb=startup_radar.validate_member_profile(p_profile); defaults jsonb; assumed jsonb=profile->'assumed_fields'; k text; v jsonb;
begin
 if p_changes is null or jsonb_typeof(p_changes)<>'object' then raise exception using errcode='22023',message='Changes must be an object'; end if;
 if p_changes ?| array['preset','assumed_fields','business_status_options'] then raise exception using errcode='22023',message='Unsupported profile field'; end if;
 if p_preset is not null then
  if p_preset not between 0 and 4 then raise exception using errcode='22023',message='Invalid preset'; end if;
  for k in select jsonb_array_elements_text(assumed) loop profile=jsonb_set(profile,array[k],'null'); end loop;
  assumed='[]'; defaults=startup_radar.profile_contract()->'presets'->p_preset;
  for k,v in select * from jsonb_each(defaults) loop
   if profile->k='null'::jsonb and not(k='business_status_options' and profile->>'business_status' is not null) then
    profile=jsonb_set(profile,array[k],v); assumed=assumed||jsonb_build_array(k);
   end if;
  end loop;
  profile=jsonb_set(profile,'{preset}',to_jsonb(p_preset));
 end if;
 select coalesce(jsonb_agg(x order by x),'[]') into assumed from jsonb_array_elements_text(assumed) x where not (p_changes ? x);
 if p_changes ? 'business_status' then profile=jsonb_set(profile,'{business_status_options}','null'); assumed=assumed-'business_status_options'; end if;
 return startup_radar.validate_member_profile(profile || p_changes || jsonb_build_object('assumed_fields',assumed));
end $$;

create table startup_radar.profile_calculation_requests (
 team_id uuid not null, profile_version integer not null,
 state text not null default 'PENDING' check(state in ('PENDING','RUNNING','SUCCESS','FAILED','SUPERSEDED')),
 requested_at timestamptz not null default now(), started_at timestamptz, finished_at timestamptz,
 attempts integer not null default 0 check(attempts>=0), error_kind text,
 primary key(team_id,profile_version),
 foreign key(team_id,profile_version) references startup_radar.team_profile_versions(team_id,version) on delete cascade
);
create index profile_calculation_pending_idx on startup_radar.profile_calculation_requests(state,requested_at);
alter table startup_radar.profile_calculation_requests enable row level security;
revoke all on startup_radar.profile_calculation_requests from public,anon,authenticated;
grant select on startup_radar.profile_calculation_requests to authenticated;
grant insert(team_id,profile_version) on startup_radar.profile_calculation_requests to authenticated;
grant all on startup_radar.profile_calculation_requests to service_role;
create policy read_profile_requests on startup_radar.profile_calculation_requests for select to authenticated using (
 (select public.my_role()) in ('member','admin') and team_id in (select m.team_id from startup_radar.team_members m where m.user_id=(select auth.uid())));
create policy insert_profile_requests on startup_radar.profile_calculation_requests for insert to authenticated with check (
 (select public.my_role()) in ('member','admin') and team_id in (select m.team_id from startup_radar.team_members m where m.user_id=(select auth.uid()) and m.role in ('OWNER','EDITOR'))
 and exists(select 1 from startup_radar.team_profiles p where p.team_id=profile_calculation_requests.team_id and p.version=profile_calculation_requests.profile_version));

-- Enforce the history/outbox contract for RPC and existing Python writes alike.
create function startup_radar.guard_profile_write() returns trigger language plpgsql security invoker set search_path='' as $$
begin
 perform startup_radar.validate_member_profile(new.profile);
 if tg_op='UPDATE' and (new.team_id<>old.team_id or new.version<>old.version+1) then
  raise exception using errcode='22023',message='Profile updates require the next immutable version'; end if;
 if tg_op='INSERT' and new.version<>1 then raise exception using errcode='22023',message='Profile must start at version 1'; end if;
 new.updated_at=now(); return new;
end $$;
create function startup_radar.guard_profile_history() returns trigger language plpgsql security invoker set search_path='' as $$
begin
 if not exists(select 1 from startup_radar.team_profiles p where p.team_id=new.team_id and p.version=new.version and p.profile=new.profile) then
  raise exception using errcode='22023',message='History must match the current profile'; end if;
 return new;
end $$;
create function startup_radar.capture_profile_change() returns trigger language plpgsql security invoker set search_path='' as $$
begin
 insert into startup_radar.team_profile_versions(team_id,version,profile) values(new.team_id,new.version,new.profile);
 insert into startup_radar.profile_calculation_requests(team_id,profile_version) values(new.team_id,new.version);
 return new;
end $$;
create trigger guard_profile_write before insert or update on startup_radar.team_profiles for each row execute function startup_radar.guard_profile_write();
create trigger guard_profile_history before insert on startup_radar.team_profile_versions for each row execute function startup_radar.guard_profile_history();
create trigger capture_profile_change after insert or update on startup_radar.team_profiles for each row execute function startup_radar.capture_profile_change();

create function public.gfc_radar_update_profile(p_team_id uuid,p_expected_version integer,p_changes jsonb default '{}',p_preset integer default null)
returns jsonb language plpgsql volatile security invoker set search_path='' as $$
declare current_profile startup_radar.team_profiles; edited startup_radar.team_profiles; membership_role text;
begin
 perform public.gfc_radar_me();
 select m.role into membership_role from startup_radar.team_members m where m.team_id=p_team_id and m.user_id=auth.uid();
 if membership_role is null or membership_role not in ('OWNER','EDITOR') then raise exception using errcode='42501',message='Team editing requires owner/editor membership'; end if;
 select * into current_profile from startup_radar.team_profiles where team_id=p_team_id for update;
 if not found then raise exception using errcode='42501',message='Team is not accessible'; end if;
 if p_expected_version is null or current_profile.version<>p_expected_version then raise exception using errcode='40001',message='Profile changed; refresh before editing'; end if;
 update startup_radar.team_profiles set profile=startup_radar.apply_member_profile(current_profile.profile,p_preset,p_changes),version=version+1 where team_id=p_team_id returning * into edited;
 return to_jsonb(edited)||jsonb_build_object('role',membership_role,'calculation_state','PENDING');
end $$;

create table startup_radar.team_creation_requests (
 request_id uuid primary key, user_id uuid not null references auth.users on delete cascade,
 team_id uuid not null references startup_radar.teams on delete cascade, name text not null, preset integer not null
);
create index team_creation_user_idx on startup_radar.team_creation_requests(user_id);
create index team_creation_team_idx on startup_radar.team_creation_requests(team_id);
alter table startup_radar.team_creation_requests enable row level security;
revoke all on startup_radar.team_creation_requests from public,anon,authenticated;
grant all on startup_radar.team_creation_requests to service_role;
-- Creation needs bootstrap authority before team membership exists. Keep that
-- authority in a private function, with explicit identity/role checks and no
-- caller-provided owner or privilege fields. Ordinary profile writes stay RLS.
create function startup_radar.create_member_team(p_name text,p_preset integer,p_request_id uuid)
returns jsonb language plpgsql volatile security definer set search_path='' as $$
declare actor uuid=auth.uid(); request startup_radar.team_creation_requests; team startup_radar.teams; profile jsonb;
begin
 if actor is null or public.my_role() not in ('member','admin') or public.my_role() is null then raise exception using errcode='42501',message='Verified GFC membership required'; end if;
 if p_request_id is null or p_name is null or length(btrim(p_name)) not between 1 and 100 or p_preset is null or p_preset not between 0 and 4 then
  raise exception using errcode='22023',message='Invalid team request'; end if;
 perform pg_advisory_xact_lock(hashtextextended(p_request_id::text,0));
 select * into request from startup_radar.team_creation_requests where request_id=p_request_id;
 if found then
  if request.user_id<>actor or request.name<>btrim(p_name) or request.preset<>p_preset then raise exception using errcode='40001',message='Creation request already used'; end if;
  if not exists(select 1 from startup_radar.team_members m where m.team_id=request.team_id and m.user_id=actor) then raise exception using errcode='42501',message='Team is not accessible'; end if;
  select * into team from startup_radar.teams where id=request.team_id; return to_jsonb(team);
 end if;
 profile=startup_radar.apply_member_profile('{}',p_preset,'{}');
 insert into startup_radar.teams(name) values(btrim(p_name)) returning * into team;
 insert into startup_radar.team_members(team_id,user_id,role) values(team.id,actor,'OWNER');
 insert into startup_radar.team_profiles(team_id,profile) values(team.id,profile);
 insert into startup_radar.team_creation_requests(request_id,user_id,team_id,name,preset) values(p_request_id,actor,team.id,btrim(p_name),p_preset);
 return to_jsonb(team);
end $$;
create function public.gfc_radar_create_team(p_name text,p_preset integer,p_request_id uuid)
returns jsonb language sql volatile security invoker set search_path='' as $$
 select startup_radar.create_member_team(p_name,p_preset,p_request_id);
$$;

revoke all on function startup_radar.profile_contract(),startup_radar.validate_member_profile(jsonb),startup_radar.apply_member_profile(jsonb,integer,jsonb),
 startup_radar.guard_profile_write(),startup_radar.guard_profile_history(),startup_radar.capture_profile_change(),
 startup_radar.create_member_team(text,integer,uuid),public.gfc_radar_create_team(text,integer,uuid),public.gfc_radar_update_profile(uuid,integer,jsonb,integer)
 from public,anon,authenticated,service_role;
grant execute on function startup_radar.profile_contract(),startup_radar.validate_member_profile(jsonb),startup_radar.apply_member_profile(jsonb,integer,jsonb),
 startup_radar.create_member_team(text,integer,uuid),public.gfc_radar_create_team(text,integer,uuid),public.gfc_radar_update_profile(uuid,integer,jsonb,integer) to authenticated;
grant execute on function startup_radar.profile_contract(),startup_radar.validate_member_profile(jsonb) to service_role;
notify pgrst,'reload schema';
commit;
