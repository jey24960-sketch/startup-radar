-- Existing GFC identities are read only; all synthetic Radar changes roll back.
create temporary table radar_profile_verification(payload jsonb) on commit drop;
do $test$
#variable_conflict use_variable
declare member_id uuid; other_id uuid; external_id uuid; team_id uuid; request_id uuid=gen_random_uuid();
 response jsonb; first_response jsonb; result jsonb; denied boolean;
begin
 select p.id into member_id from public.profiles p join auth.users u on u.id=p.id where p.role='member' and u.deleted_at is null and not u.is_anonymous order by p.id limit 1;
 select p.id into other_id from public.profiles p join auth.users u on u.id=p.id where p.role='member' and p.id<>member_id and u.deleted_at is null and not u.is_anonymous order by p.id limit 1;
 select p.id into external_id from public.profiles p join auth.users u on u.id=p.id where p.role='external' and u.deleted_at is null and not u.is_anonymous order by p.id limit 1;
 assert member_id is not null and other_id is not null and external_id is not null, 'Existing roles required';
 begin
  perform set_config('request.jwt.claim.sub','',true); set local role anon;
  denied=false; begin perform public.gfc_radar_create_team('Denied',0,request_id); exception when insufficient_privilege then denied=true; end; assert denied,'Anonymous create allowed';
  denied=false; begin perform public.gfc_radar_update_profile(request_id,1); exception when insufficient_privilege then denied=true; end; assert denied,'Anonymous update allowed';
  reset role;
  perform set_config('request.jwt.claim.sub',external_id::text,true); set local role authenticated;
  denied=false; begin perform public.gfc_radar_create_team('Denied',0,request_id); exception when insufficient_privilege then denied=true; end; assert denied,'External create allowed';
  reset role;
  perform set_config('request.jwt.claim.sub',member_id::text,true); set local role authenticated;
  first_response=public.gfc_radar_create_team('[ROLLBACK PROFILE TEST]',0,request_id); team_id=(first_response->>'id')::uuid;
  assert public.gfc_radar_create_team('[ROLLBACK PROFILE TEST]',0,request_id)=first_response,'Creation retry duplicated';
  response=public.gfc_radar_me();
  assert exists(select 1 from jsonb_array_elements(response->'teams') t where t->>'id'=team_id::text and t->>'role'='OWNER' and t->'profile'->>'team_status'='PRE_TEAM' and t->'profile'->'founder_age'='null'::jsonb and t->'profile'->'has_revenue'='false'::jsonb),'Stage 0 owner/UNKNOWN mismatch';
  response=public.gfc_radar_update_profile(team_id,1,'{"founder_age":null,"student_status":false,"region":"Seoul"}',null);
  assert response->>'version'='2' and response->>'calculation_state'='PENDING','Profile response not versioned/pending';
  assert (select count(*) from startup_radar.team_profile_versions v where v.team_id=team_id)=2,'History not captured';
  assert (select count(*) from startup_radar.profile_calculation_requests r where r.team_id=team_id and r.state='PENDING')=2,'Atomic requests missing';
  denied=false; begin perform public.gfc_radar_update_profile(team_id,1,'{}'); exception when serialization_failure then denied=true; end; assert denied,'Stale save accepted';
  denied=false; begin perform public.gfc_radar_update_profile(team_id,2,'{"founder_age":121}'); exception when invalid_parameter_value then denied=true; end; assert denied,'Invalid age accepted';
  denied=false; begin update startup_radar.team_profiles p set profile='{}' where p.team_id=team_id; exception when invalid_parameter_value then denied=true; end; assert denied,'Raw write skipped version/history';
  denied=false; begin update startup_radar.profile_calculation_requests r set state='SUCCESS' where r.team_id=team_id; exception when insufficient_privilege then denied=true; end; assert denied,'Member forged worker result';
  reset role;
  perform set_config('request.jwt.claim.sub',other_id::text,true); set local role authenticated;
  denied=false; begin perform public.gfc_radar_update_profile(team_id,2,'{}'); exception when insufficient_privilege then denied=true; end; assert denied,'Foreign team edit allowed';
  reset role;
  insert into startup_radar.team_members(team_id,user_id,role) values(team_id,other_id,'MEMBER'),(team_id,external_id,'EDITOR');
  set local role authenticated;
  denied=false; begin perform public.gfc_radar_update_profile(team_id,2,'{}'); exception when insufficient_privilege then denied=true; end; assert denied,'Viewer edit allowed';
  reset role;
  perform set_config('request.jwt.claim.sub',external_id::text,true); set local role authenticated;
  denied=false; begin perform public.gfc_radar_update_profile(team_id,2,'{}'); exception when insufficient_privilege then denied=true; end; assert denied,'External stray editor allowed';
  reset role;
  assert (select p.version from startup_radar.team_profiles p where p.team_id=team_id)=2,'Rejected write changed profile';
  result=jsonb_build_object('status','PASS','synthetic_rows_rolled_back',true,'auth_profiles_modified',false,
   'checks',jsonb_build_array('anonymous create/update denied','external create denied','retry returns same team','owner binding and Stage 0 UNKNOWN preserved',
    'profile/history/request atomic and pending','stale version denied','invalid profile denied','raw write cannot skip version','member cannot forge queue success',
    'foreign team denied','viewer denied','external stray editor denied','rejected changes leave version intact'));
  raise exception using errcode='ZX001',message='Intentional rollback';
 exception when sqlstate 'ZX001' then null;
 end;
 assert not exists(select 1 from startup_radar.teams t where t.id=team_id),'Fixture rollback failed';
 insert into pg_temp.radar_profile_verification values(result);
end $test$;
select payload from pg_temp.radar_profile_verification;
