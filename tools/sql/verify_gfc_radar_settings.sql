-- No external messages. All synthetic team/channel/preferences/audit rows roll back.
create temporary table radar_settings_verification(payload jsonb) on commit drop;
do $test$
#variable_conflict use_variable
declare member_id uuid; other_id uuid; external_id uuid; admin_id uuid; team_id uuid;
 response jsonb; result jsonb; denied boolean; flags jsonb='{"enabled":false,"digest_enabled":true,"alerts_enabled":false,"reminders_enabled":true}';
begin
 select p.id into member_id from public.profiles p join auth.users u on u.id=p.id where p.role='member' and u.deleted_at is null and not u.is_anonymous order by p.id limit 1;
 select p.id into other_id from public.profiles p join auth.users u on u.id=p.id where p.role='member' and p.id<>member_id and u.deleted_at is null and not u.is_anonymous order by p.id limit 1;
 select p.id into external_id from public.profiles p join auth.users u on u.id=p.id where p.role='external' and u.deleted_at is null and not u.is_anonymous order by p.id limit 1;
 select p.id into admin_id from public.profiles p join auth.users u on u.id=p.id where p.role='admin' and u.deleted_at is null and not u.is_anonymous order by p.id limit 1;
 assert member_id is not null and other_id is not null and external_id is not null and admin_id is not null,'Existing roles required';
 begin
  perform set_config('request.jwt.claim.sub','',true);set local role anon;
  denied=false;begin perform public.gfc_radar_health();exception when insufficient_privilege then denied=true;end;assert denied,'Anonymous health allowed';
  denied=false;begin perform public.gfc_radar_preferences(gen_random_uuid());exception when insufficient_privilege then denied=true;end;assert denied,'Anonymous preferences allowed';
  reset role;perform set_config('request.jwt.claim.sub',member_id::text,true);set local role authenticated;
  response=public.gfc_radar_create_team('[ROLLBACK SETTINGS TEST]',0,gen_random_uuid());team_id=(response->>'id')::uuid;
  response=public.gfc_radar_preferences(team_id);assert response->>'connected'='false','Unlinked channel misreported';
  response=public.gfc_radar_save_preferences(team_id,flags);assert response->'preferences'=flags,'Unlinked preferences not saved';
  denied=false;begin perform public.gfc_radar_health();exception when insufficient_privilege then denied=true;end;assert denied,'Member health allowed';
  reset role;
  insert into startup_radar.telegram_subscriptions(team_id,chat_id) values(team_id,'ROLLBACK_PRIVATE_CHAT_CANARY');
  insert into startup_radar.team_members(team_id,user_id,role) values(team_id,external_id,'EDITOR');
  set local role authenticated;
  response=public.gfc_radar_preferences(team_id);assert response->>'connected'='true' and response->'preferences'=flags,'Linked state or stored preference missing';
  assert position('CANARY' in response::text)=0 and position('chat_id' in response::text)=0,'Channel identifier leaked';
  response=public.gfc_radar_save_preferences(team_id,flags);assert response->>'updated'='1','Linked preference update missing';
  denied=false;begin perform public.gfc_radar_save_preferences(team_id,'{"enabled":"false"}');exception when invalid_parameter_value then denied=true;end;assert denied,'Invalid flags accepted';
  reset role;
  assert exists(select 1 from startup_radar.telegram_subscriptions s where s.team_id=team_id and not s.enabled and not s.alerts_enabled),'Channel flags not synchronized';
  assert (select count(*) from startup_radar.admin_audit a where a.entity_id=team_id::text and a.action='TEAM_NOTIFICATION_PREFERENCES')=2,'Audit missing';
  perform set_config('request.jwt.claim.sub',other_id::text,true);set local role authenticated;
  denied=false;begin perform public.gfc_radar_preferences(team_id);exception when insufficient_privilege then denied=true;end;assert denied,'Foreign preferences allowed';
  reset role;insert into startup_radar.team_members(team_id,user_id,role) values(team_id,other_id,'MEMBER');set local role authenticated;
  response=public.gfc_radar_preferences(team_id);assert response->>'connected'='true','Viewer read denied';
  denied=false;begin perform public.gfc_radar_save_preferences(team_id,flags);exception when insufficient_privilege then denied=true;end;assert denied,'Viewer write allowed';
  reset role;perform set_config('request.jwt.claim.sub',external_id::text,true);set local role authenticated;
  denied=false;begin perform public.gfc_radar_preferences(team_id);exception when insufficient_privilege then denied=true;end;assert denied,'External stray editor allowed';
  denied=false;begin perform public.gfc_radar_health();exception when insufficient_privilege then denied=true;end;assert denied,'External health allowed';
  reset role;perform set_config('request.jwt.claim.sub',admin_id::text,true);set local role authenticated;
  response=public.gfc_radar_health();assert jsonb_typeof(response->'sources')='array' and response ? 'calculation_queue','GFC admin health unavailable';
  assert not exists(select 1 from jsonb_array_elements(response->'sources') s where s ? 'config' or s ? 'chat_id'),'Raw operational data leaked';
  reset role;
  result=jsonb_build_object('status','PASS','synthetic_rows_rolled_back',true,'auth_profiles_modified',false,'messages_sent',0,
   'checks',jsonb_build_array('anonymous preferences/health denied','unlinked preferences persist','member health denied','linked state without channel identifier',
    'preference flags synchronized with audit','invalid flags denied','foreign preferences denied','viewer read allowed and write denied',
    'external stray editor denied','external health denied','GFC admin health allowed with safe projection'));
  raise exception using errcode='ZX001',message='Intentional rollback';
 exception when sqlstate 'ZX001' then null;
 end;
 assert not exists(select 1 from startup_radar.teams t where t.id=team_id),'Fixture rollback failed';
 insert into pg_temp.radar_settings_verification values(result);
end $test$;
select payload from pg_temp.radar_settings_verification;
