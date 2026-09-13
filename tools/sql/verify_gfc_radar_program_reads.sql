-- Existing Auth identities are read only. All synthetic Radar rows roll back.
-- This is database-role validation, not a real OAuth/browser acceptance test.
create temporary table radar_program_verification(payload jsonb) on commit drop;
do $test$
declare
 member_id uuid; other_id uuid; external_id uuid; admin_id uuid;
 team_a uuid; team_b uuid; program_id uuid; version_id uuid; generation text;
 response jsonb; result jsonb; denied boolean;
begin
 select p.id into member_id from public.profiles p join auth.users u on u.id=p.id where p.role='member' and u.deleted_at is null and not u.is_anonymous order by p.id limit 1;
 select p.id into other_id from public.profiles p join auth.users u on u.id=p.id where p.role='member' and p.id<>member_id and u.deleted_at is null and not u.is_anonymous order by p.id limit 1;
 select p.id into external_id from public.profiles p join auth.users u on u.id=p.id where p.role='external' and u.deleted_at is null and not u.is_anonymous order by p.id limit 1;
 select p.id into admin_id from public.profiles p join auth.users u on u.id=p.id where p.role='admin' and u.deleted_at is null and not u.is_anonymous order by p.id limit 1;
 select p.id,p.current_version_id into program_id,version_id from startup_radar.programs p where p.current_version_id is not null order by p.id limit 1;
 assert member_id is not null and other_id is not null and external_id is not null and admin_id is not null and program_id is not null, 'Existing identities and actual program required';
 begin
  insert into startup_radar.teams(name) values('[ROLLBACK PROGRAM RPC TEST] A') returning id into team_a;
  insert into startup_radar.teams(name) values('[ROLLBACK PROGRAM RPC TEST] B') returning id into team_b;
  insert into startup_radar.team_members(team_id,user_id,role) values(team_a,member_id,'OWNER'),(team_a,external_id,'MEMBER'),(team_b,other_id,'OWNER');
  insert into startup_radar.team_profiles(team_id,profile) values(team_a,'{"preset":0,"founder_age":null}'),(team_b,'{"region":"PRIVATE_OTHER_TEAM"}');
  perform set_config('request.jwt.claim.sub','',true);
  set local role anon;
  denied=false; begin perform public.gfc_radar_programs(); exception when insufficient_privilege then denied=true; end;
  assert denied, 'Anonymous feed leak';
  denied=false; begin perform public.gfc_radar_program_detail(program_id); exception when insufficient_privilege then denied=true; end;
  assert denied, 'Anonymous detail leak';
  reset role;
  perform set_config('request.jwt.claim.sub',external_id::text,true);
  set local role authenticated;
  denied=false; begin perform public.gfc_radar_programs(); exception when insufficient_privilege then denied=true; end;
  assert denied, 'External feed leak';
  denied=false; begin perform public.gfc_radar_program_detail(program_id,team_a); exception when insufficient_privilege then denied=true; end;
  assert denied, 'External with stray membership detail leak';
  assert (select count(*) from startup_radar.member_program_results)=0, 'External raw results leak';
  reset role;
  perform set_config('request.jwt.claim.sub',member_id::text,true);
  set local role authenticated;
  response=public.gfc_radar_program_detail(program_id,team_a);
  assert response->>'calculation_state'='PENDING' and response->'eligibility'='null'::jsonb, 'Uncomputed must remain pending';
  assert response->'facts'->>'title' is not null and jsonb_array_length(response->'versions')>0, 'Actual facts/version unavailable';
  assert not exists(select 1 from jsonb_array_elements(response->'documents') d where d ? 'extracted_text' or d ? 'error_message'), 'Unsafe document DTO';
  response=public.gfc_radar_programs(p_preset=>0,p_history=>true);
  assert (response->>'total')::integer>=1, 'Stage 0 actual feed unavailable';
  denied=false; begin perform public.gfc_radar_program_detail(program_id,team_b); exception when insufficient_privilege then denied=true; end;
  assert denied, 'Foreign team detail leak';
  reset role;
  select s.generation into generation from startup_radar.member_read_state s where singleton;
  insert into startup_radar.member_program_results(scope_key,program_version_id,team_id,profile_version,profile_snapshot,evaluated_on,generation,eligibility)
   select t.team_id::text,version_id,t.team_id,t.version,t.profile,(now() at time zone 'Asia/Seoul')::date,generation,
     case when t.team_id=team_a then '{"status":"ELIGIBLE"}'::jsonb else '{"status":"INELIGIBLE"}'::jsonb end
   from startup_radar.team_profiles t where t.team_id in (team_a,team_b);
  set local role authenticated;
  response=public.gfc_radar_program_detail(program_id,team_a);
  assert response->>'calculation_state'='READY' and response->'eligibility'->>'status'='ELIGIBLE', 'Own stored result missing';
  assert (select count(*) from startup_radar.member_program_results r where r.team_id=team_b)=0, 'Raw foreign team result leak';
  denied=false; begin update startup_radar.member_program_results set eligibility='{}' where team_id=team_a; exception when insufficient_privilege then denied=true; end;
  assert denied, 'Member must not author engine results';
  reset role;
  update startup_radar.team_profiles t set version=version+1 where t.team_id=team_a;
  set local role authenticated;
  response=public.gfc_radar_program_detail(program_id,team_a);
  assert response->>'calculation_state'='PENDING' and response->'eligibility'='null'::jsonb, 'Stale profile result leak';
  reset role;
  perform set_config('request.jwt.claim.sub',admin_id::text,true);
  set local role authenticated;
  response=public.gfc_radar_programs(p_preset=>0,p_history=>true);
  assert (response->>'total')::integer>=1, 'GFC admin preset denied';
  denied=false; begin perform public.gfc_radar_program_detail(program_id,team_a); exception when insufficient_privilege then denied=true; end;
  assert denied, 'Admin feed scope must preserve team isolation';
  reset role;
  result=jsonb_build_object('status','PASS','synthetic_rows_rolled_back',true,'auth_profiles_modified',false,'actual_program_facts_read',true,
   'checks',jsonb_build_array('anonymous feed/detail denied','external feed/detail denied despite stray membership','external raw results denied',
   'uncomputed eligibility remains null pending','actual facts/version and safe documents accessible','Stage 0 without team accessible',
   'foreign team detail denied','own stored result accessible','raw foreign team result denied','member result write denied',
   'stale profile result hidden','admin preset allowed and private team denied'));
  raise exception using errcode='ZX001',message='Intentional rollback of synthetic program RPC fixtures';
 exception when sqlstate 'ZX001' then null;
 end;
 assert not exists(select 1 from startup_radar.teams where id in (team_a,team_b)), 'Fixture rollback failed';
 insert into pg_temp.radar_program_verification values(result);
end $test$;
select payload from pg_temp.radar_program_verification;
