-- Read existing GFC identities; never modify Auth or public.profiles.
-- Synthetic Radar records and role switches are rolled back before returning.
create temporary table radar_context_verification(payload jsonb) on commit drop;
do $test$
declare
 member_id uuid; other_id uuid; external_id uuid; admin_id uuid;
 team_a uuid; team_b uuid; context jsonb; result jsonb; denied boolean;
begin
 select p.id into member_id from public.profiles p join auth.users u on u.id=p.id where p.role='member' and u.deleted_at is null and not u.is_anonymous order by p.id limit 1;
 select p.id into other_id from public.profiles p join auth.users u on u.id=p.id where p.role='member' and p.id<>member_id and u.deleted_at is null and not u.is_anonymous order by p.id limit 1;
 select p.id into external_id from public.profiles p join auth.users u on u.id=p.id where p.role='external' and u.deleted_at is null and not u.is_anonymous order by p.id limit 1;
 select p.id into admin_id from public.profiles p join auth.users u on u.id=p.id where p.role='admin' and u.deleted_at is null and not u.is_anonymous order by p.id limit 1;
 assert member_id is not null and other_id is not null and external_id is not null and admin_id is not null, 'Existing role identities required';
 begin
  insert into startup_radar.teams(name) values('[ROLLBACK RPC TEST] A') returning id into team_a;
  insert into startup_radar.teams(name) values('[ROLLBACK RPC TEST] B') returning id into team_b;
  insert into startup_radar.team_members(team_id,user_id,role) values(team_a,member_id,'OWNER'),(team_a,external_id,'MEMBER'),(team_b,other_id,'OWNER');
  insert into startup_radar.team_profiles(team_id,profile) values(team_a,'{"preset":0,"founder_age":null}'),(team_b,'{"region":"PRIVATE_OTHER_TEAM"}');
  perform set_config('request.jwt.claim.sub','',true);
  set local role anon;
  denied=false;
  begin perform public.gfc_radar_me(); exception when insufficient_privilege then denied=true; end;
  assert denied, 'Anonymous RPC must be denied';
  reset role;
  perform set_config('request.jwt.claim.sub',external_id::text,true);
  set local role authenticated;
  denied=false;
  begin perform public.gfc_radar_me(); exception when insufficient_privilege then denied=true; end;
  assert denied, 'External with stray Radar membership must be denied';
  reset role;
  perform set_config('request.jwt.claim.sub',member_id::text,true);
  set local role authenticated;
  context=public.gfc_radar_me();
  assert context->>'user_id'=member_id::text and context->>'is_admin'='false', 'Wrong member identity';
  assert exists(select 1 from jsonb_array_elements(context->'teams') t where t->>'id'=team_a::text and t->'profile'->>'preset'='0' and t->'profile'->'founder_age'='null'::jsonb), 'Own Stage 0 missing';
  assert not exists(select 1 from jsonb_array_elements(context->'teams') t where t->>'id'=team_b::text), 'Cross-team leak';
  assert position('PRIVATE_OTHER_TEAM' in context::text)=0, 'Private field leak';
  reset role;
  perform set_config('request.jwt.claim.sub',admin_id::text,true);
  set local role authenticated;
  context=public.gfc_radar_me();
  assert context->>'is_admin'='true', 'GFC admin not recognized';
  assert not exists(select 1 from jsonb_array_elements(context->'teams') t where t->>'id' in (team_a::text,team_b::text)), 'Admin context must still respect team isolation';
  reset role;
  result=jsonb_build_object('status','PASS','synthetic_rows_rolled_back',true,'auth_profiles_modified',false,
    'checks',jsonb_build_array('anonymous RPC denied','external with stray membership denied','own-team Stage 0 and UNKNOWN preserved','cross-team profile denied','GFC admin recognized without cross-team access'));
  raise exception using errcode='ZX001',message='Intentional rollback of synthetic RPC fixtures';
 exception when sqlstate 'ZX001' then null;
 end;
 assert not exists(select 1 from startup_radar.teams where id in (team_a,team_b)), 'Fixture rollback failed';
 insert into pg_temp.radar_context_verification values(result);
end $test$;
select payload from pg_temp.radar_context_verification;
