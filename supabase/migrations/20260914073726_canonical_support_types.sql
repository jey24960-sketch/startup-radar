begin;
set local lock_timeout='3s';
set local statement_timeout='30s';

-- Generated contract from radar.support_types.contract(); parity is tested.
create function startup_radar.support_type_contract() returns jsonb
language sql immutable security invoker set search_path='' as $contract$
 select $json${"version":1,"types":[{"value":"GRANT","label":"사업화 지원"},{"value":"COMPETITION","label":"경진대회"},{"value":"INCUBATION","label":"보육"},{"value":"ACCELERATION","label":"액셀러레이팅"},{"value":"INVESTMENT_LINKED","label":"투자 연계"},{"value":"WORKSPACE","label":"공간 지원"},{"value":"GLOBAL","label":"해외 진출"},{"value":"MARKET_ENTRY","label":"판로 지원"},{"value":"EDUCATION","label":"교육"},{"value":"MENTORING","label":"멘토링"},{"value":"CONSULTING","label":"컨설팅"},{"value":"POLICY_LOAN","label":"정책 융자"},{"value":"SME_FINANCING","label":"중소기업 금융"},{"value":"GENERIC_RD","label":"연구개발"},{"value":"UNKNOWN","label":"분류 미확인"}],"raw_mapping":{"사업화":["GRANT"],"시설ㆍ공간ㆍ보육":["WORKSPACE","INCUBATION"],"멘토링ㆍ컨설팅ㆍ교육":["MENTORING","CONSULTING","EDUCATION"],"글로벌":["GLOBAL"],"수출":["GLOBAL"],"판로ㆍ해외진출":["MARKET_ENTRY","GLOBAL"],"기술개발(R&D)":["GENERIC_RD"],"융자":["POLICY_LOAN"]}}$json$::jsonb;
$contract$;

create function startup_radar.normalize_support_types(raw_types text[]) returns text[]
language sql immutable security invoker set search_path='' as $$
 with expanded as (
  select r.ordinality source_order,m.ordinality mapping_order,m.value
  from unnest(raw_types) with ordinality r(value,ordinality)
  cross join lateral jsonb_array_elements_text(
   case when exists (select 1 from jsonb_array_elements(startup_radar.support_type_contract()->'types') t where t->>'value'=r.value)
    then jsonb_build_array(r.value)
    else coalesce(startup_radar.support_type_contract()->'raw_mapping'->r.value,'["UNKNOWN"]'::jsonb) end
  ) with ordinality m(value,ordinality)
 ), first_occurrence as (
  select distinct on(value) * from expanded order by value,source_order,mapping_order
 )
 select coalesce(array_agg(value order by source_order,mapping_order),array['UNKNOWN']) from first_occurrence;
$$;
revoke all on function startup_radar.support_type_contract(),startup_radar.normalize_support_types(text[]) from public,anon,authenticated,service_role;
grant execute on function startup_radar.support_type_contract(),startup_radar.normalize_support_types(text[]) to authenticated,service_role;

-- Read projection only. Immutable version JSON and raw source snapshots are not rewritten.
create or replace function public.gfc_radar_me()
returns jsonb language plpgsql stable security invoker set search_path = ''
as $$
declare
  current_user_id uuid := auth.uid();
  gfc_role text := public.my_role();
  member_teams jsonb;
begin
  if current_user_id is null or gfc_role is null or gfc_role not in ('member','admin') then
    raise exception using errcode = '42501', message = 'Verified GFC membership required';
  end if;
  select coalesce(jsonb_agg(jsonb_build_object(
    'id', t.id, 'name', t.name, 'role', m.role,
    'profile', p.profile, 'version', p.version
  ) order by t.created_at,t.id), '[]'::jsonb) into member_teams
  from startup_radar.teams t
  join startup_radar.team_members m on m.team_id=t.id
  join startup_radar.team_profiles p on p.team_id=t.id
  where m.user_id=current_user_id;
  return jsonb_build_object('user_id',current_user_id,'is_admin',gfc_role='admin','teams',member_teams,'support_types',startup_radar.support_type_contract()->'types');
end;
$$;

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
 return jsonb_build_object('id',v.program_id,'version_id',v.id,'version',v.version,'facts',v.normalized || jsonb_build_object('program_types',to_jsonb(startup_radar.normalize_support_types(array(select jsonb_array_elements_text(v.normalized->'program_types'))))),
  'updated_at',v.created_at,'status',live_status,
  'program_responses',jsonb_build_object('responses',answers,'revision',answer_revision),
  'days_left',(end_at at time zone 'Asia/Seoul')::date-(now() at time zone 'Asia/Seoul')::date,
  'calculation_state',case when r.program_version_id is not null then 'READY' when config.state='FAILED' then 'FAILED' else 'PENDING' end,
  'eligibility',r.eligibility,'recommendation',case when live_status in ('OPEN','UPCOMING') then r.recommendation else null end,
  'evaluation_profile',r.profile_snapshot,'evaluation_responses',r.response_snapshot,
  'computed_at',r.computed_at);
end $$;

create or replace function public.gfc_radar_programs(
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
 if p_program_type is not null and not exists (
  select 1 from jsonb_array_elements(startup_radar.support_type_contract()->'types') t where t->>'value'=p_program_type
 ) then raise exception using errcode='22023',message='Invalid support type'; end if;
 with candidates as materialized (
  select p.id,p.updated_at,p.application_end_at,startup_radar.member_program_item(p.current_version_id,scope) item
  from startup_radar.programs p where p.current_version_id is not null
   and (coalesce(p_q,'')='' or p.title ilike '%'||p_q||'%' or p.organization ilike '%'||p_q||'%')
   and (p_program_type is null or p_program_type=any(startup_radar.normalize_support_types(p.program_types)))
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

-- Generated from tools.profile_contract; all profile enum items share the Python contract.
create or replace function startup_radar.profile_contract() returns jsonb language sql immutable security invoker set search_path='' as $contract$
 select $json${"defaults":{"age_band":null,"applicant_type":null,"assumed_fields":[],"business_age_months":null,"business_registration_date":null,"business_status":null,"business_status_options":null,"founder_age":null,"global_expansion_interest":null,"has_revenue":null,"industry":null,"investment_received":null,"investment_stage":null,"preferred_program_types":null,"preset":null,"prior_support_restrictions":null,"product_stage":null,"region":null,"revenue":null,"revenue_band":null,"student_status":null,"team_size":null,"team_status":null,"university_affiliation":null},"fields":{"age_band":{"maxItems":2,"minItems":2,"nullable":true,"type":"array"},"applicant_type":{"nullable":true,"type":"string"},"assumed_fields":{"items":{"type":"string"},"nullable":false,"type":"array"},"business_age_months":{"minimum":0,"nullable":true,"type":"integer"},"business_registration_date":{"format":"date","nullable":true,"type":"string"},"business_status":{"enum":["PRE_BUSINESS","SOLE_PROPRIETOR","CORPORATION"],"nullable":true,"type":"string"},"business_status_options":{"items":{"enum":["PRE_BUSINESS","SOLE_PROPRIETOR","CORPORATION"],"type":"string"},"nullable":true,"type":"array"},"founder_age":{"maximum":120,"minimum":0,"nullable":true,"type":"integer"},"global_expansion_interest":{"nullable":true,"type":"boolean"},"has_revenue":{"nullable":true,"type":"boolean"},"industry":{"items":{"type":"string"},"nullable":true,"type":"array"},"investment_received":{"nullable":true,"type":"boolean"},"investment_stage":{"nullable":true,"type":"string"},"preferred_program_types":{"items":{"enum":["GRANT","COMPETITION","INCUBATION","ACCELERATION","INVESTMENT_LINKED","WORKSPACE","GLOBAL","MARKET_ENTRY","EDUCATION","MENTORING","CONSULTING","POLICY_LOAN","SME_FINANCING","GENERIC_RD","UNKNOWN"],"type":"string"},"nullable":true,"type":"array"},"preset":{"maximum":4,"minimum":0,"nullable":true,"type":"integer"},"prior_support_restrictions":{"items":{"type":"string"},"nullable":true,"type":"array"},"product_stage":{"enum":["IDEA","LANDING","MVP","REVENUE"],"nullable":true,"type":"string"},"region":{"nullable":true,"type":"string"},"revenue":{"minimum":0,"nullable":true,"type":"number"},"revenue_band":{"nullable":true,"type":"string"},"student_status":{"nullable":true,"type":"boolean"},"team_size":{"maximum":10000,"minimum":1,"nullable":true,"type":"integer"},"team_status":{"enum":["PRE_TEAM","FORMING","TEAMED"],"nullable":true,"type":"string"},"university_affiliation":{"nullable":true,"type":"string"}},"presets":[{"business_status":"PRE_BUSINESS","has_revenue":false,"product_stage":"IDEA","team_status":"PRE_TEAM"},{"business_status":"PRE_BUSINESS","product_stage":"IDEA","team_status":"TEAMED"},{"business_status":"PRE_BUSINESS","product_stage":"LANDING","team_status":"TEAMED"},{"product_stage":"MVP","team_status":"TEAMED"},{"business_status_options":["SOLE_PROPRIETOR","CORPORATION"]}]}$json$::jsonb;
$contract$;

notify pgrst,'reload schema';
commit;
