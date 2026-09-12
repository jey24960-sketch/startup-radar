-- Run only after the startup_radar baseline. Never resets production fixtures.
-- All application seed writes and temporary role changes roll back inside the
-- exception subtransaction. Only the redacted verification report survives.
create temporary table radar_staging_verification_report(payload jsonb) on commit drop;
do $test$
declare
 users uuid[];
 teams uuid[] := '{}';
 team uuid;
 item jsonb;
 profiles jsonb := '[
  {"name":"Stage 0","profile":{"team_status":"PRE_TEAM","product_stage":"IDEA","business_status":"PRE_BUSINESS","has_revenue":false,"preset":0}},
  {"name":"Team Idea","profile":{"team_status":"TEAMED","product_stage":"IDEA","business_status":"PRE_BUSINESS","preset":1}},
  {"name":"Landing","profile":{"team_status":"TEAMED","product_stage":"LANDING","business_status":"PRE_BUSINESS","preset":2}},
  {"name":"MVP PRE_BUSINESS","profile":{"team_status":"TEAMED","product_stage":"MVP","business_status":"PRE_BUSINESS","preset":3}},
  {"name":"MVP CORPORATION","profile":{"team_status":"TEAMED","product_stage":"MVP","business_status":"CORPORATION","preset":4}}
 ]';
 changed integer;
 denied boolean;
 result jsonb;
 program_id uuid;
 version_id uuid;
 notice jsonb := '{"title":"[STAGING FIXTURE] 법인 전용 지원사업","organization":"Synthetic test only","official_url":"https://example.invalid/staging/corporation-only","program_types":["GRANT"],"deadline_type":"ROLLING","evidence_complete":true,"requirements":[{"key":"business_status","operator":"EQ","value":"CORPORATION","certain":true,"mandatory":true,"evidence":[{"source_id":"staging-fixture","text":"검증용 가상 공고: 법인만 지원 가능","method":"MANUAL","verified":true,"confidence":1}]}]}';
begin
 select array_agg(id order by id) into users from
  (select id from auth.users u where deleted_at is null and not is_anonymous
   and not exists(select 1 from startup_radar.admin_users a where a.user_id=u.id)
   and not exists(select 1 from startup_radar.team_members m where m.user_id=u.id)
   order by id limit 3) u;
 assert array_length(users,1)=3, 'Three existing Auth identities required; never creates test Auth users';
 begin
  for item in select value from jsonb_array_elements(profiles) loop
   insert into startup_radar.teams(name) values('[STAGING ROLLBACK] '||(item->>'name')) returning id into team;
   teams := array_append(teams,team);
   insert into startup_radar.team_profiles(team_id,profile) values(team,item->'profile');
   insert into startup_radar.team_profile_versions(team_id,version,profile) values(team,1,item->'profile');
  end loop;
  insert into startup_radar.team_members(team_id,user_id,role) values(teams[1],users[1],'OWNER'),(teams[5],users[2],'OWNER');
  insert into startup_radar.telegram_subscriptions(team_id,chat_id,enabled) values(teams[1],'staging-not-a-real-chat',false);
  insert into startup_radar.programs(canonical_key,title,organization,program_types,status,deadline_type,official_url)
   values('staging:'||gen_random_uuid()::text,notice->>'title',notice->>'organization',array['GRANT'],'OPEN','ROLLING',notice->>'official_url') returning id into program_id;
  insert into startup_radar.program_versions(program_id,version,content_hash,normalized,evidence_complete)
   values(program_id,1,md5(notice::text),notice,true) returning id into version_id;
  update startup_radar.programs p set current_version_id=version_id where p.id=program_id;
  insert into startup_radar.program_requirements(program_version_id,requirement)
   select version_id,value from jsonb_array_elements(notice->'requirements');

  perform set_config('request.jwt.claim.sub',users[1]::text,true);
  set local role authenticated;
  assert (select count(*)=1 from startup_radar.team_profiles where team_id=any(teams)), 'Cross-team profile read leaked';
  assert (select count(*)=1 from startup_radar.team_profile_versions where team_id=any(teams)), 'Cross-team history read leaked';
  assert (select count(*)=0 from startup_radar.telegram_subscriptions where team_id=any(teams)), 'Telegram ID leaked';
  update startup_radar.team_profiles set profile='{}' where team_id=teams[5];
  get diagnostics changed = row_count;
  assert changed=0, 'Cross-team update was allowed';
  denied:=false;
  begin
   insert into startup_radar.team_profile_versions(team_id,version,profile) values(teams[5],2,'{}');
  exception when insufficient_privilege then denied:=true;
  end;
  assert denied, 'Cross-team history insert was allowed';
  denied:=false;
  begin
   update startup_radar.team_profiles set team_id=teams[5] where team_id=teams[1];
  exception when insufficient_privilege then denied:=true;
  end;
  assert denied, 'Profile reassignment was allowed';
  denied:=false;
  begin
   insert into startup_radar.admin_users values(users[1]);
  exception when insufficient_privilege then denied:=true;
  end;
  assert denied, 'Admin self-escalation was allowed';
  reset role;

  perform set_config('request.jwt.claim.sub',users[2]::text,true);
  set local role authenticated;
  assert (select count(*)=1 from startup_radar.team_profiles where team_id=any(teams)), 'Second team read isolation failed';
  assert (select profile->>'business_status'='CORPORATION' from startup_radar.team_profiles where team_id=teams[5]), 'Second team profile mismatch';
  reset role;

  perform set_config('request.jwt.claim.sub',users[3]::text,true);
  set local role authenticated;
  assert (select count(*)=0 from startup_radar.team_profiles where team_id=any(teams)), 'Shared Auth without Radar membership gained access';
  reset role;

  insert into startup_radar.admin_users values(users[1]);
  perform set_config('request.jwt.claim.sub',users[1]::text,true);
  set local role authenticated;
  assert (select count(*)=1 from startup_radar.telegram_subscriptions where team_id=any(teams)), 'Administrator operational access failed';
  assert (select count(*)=1 from startup_radar.team_profiles where team_id=any(teams)), 'Administrator membership-scoped profile isolation failed';
  reset role;

  set local role anon;
  denied:=false;
  begin
   perform count(*) from startup_radar.team_profiles;
  exception when insufficient_privilege then denied:=true;
  end;
  assert denied, 'Anonymous access was allowed';
  reset role;

  set local role service_role;
  assert (select count(*)=5 from startup_radar.team_profiles where team_id=any(teams)), 'Service role read failed';
  update startup_radar.team_profiles set version=version where team_id=teams[1];
  get diagnostics changed=row_count;
  assert changed=1, 'Service role write failed';
  reset role;

  select jsonb_build_object('status','PASS','seed_rolled_back',true,'auth_users_created',0,
   'program',(select normalized from startup_radar.program_versions v where v.id=version_id),
   'scenarios',(select jsonb_agg(jsonb_build_object('name',t.name,'profile',p.profile,'version',p.version) order by t.name)
      from startup_radar.teams t join startup_radar.team_profiles p on p.team_id=t.id where t.id=any(teams)),
   'checks',jsonb_build_array('auth.users foreign keys','owner profile read','second team isolation','cross-team update denied',
     'cross-team version insert denied','profile reassignment denied','admin escalation denied',
     'nonmember denied','Telegram privacy','administrator operational access','anonymous denied','service role read/write')) into result;
  raise exception using errcode='ZX001',message='Intentional rollback of staging seed';
 exception when sqlstate 'ZX001' then
  null;
 end;
 assert (select count(*)=0 from startup_radar.teams t where t.id=any(teams)), 'Staging seed rollback failed';
 insert into pg_temp.radar_staging_verification_report values(result);
end $test$;
select payload from pg_temp.radar_staging_verification_report;
