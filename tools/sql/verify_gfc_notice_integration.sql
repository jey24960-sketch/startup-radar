-- Uses existing role-bearing identities without changing their profiles.
-- Every synthetic notice/team and every role switch is rolled back.
create temporary table gfc_notice_verification(payload jsonb) on commit drop;
do $test$
declare
 member_id uuid; external_id uuid; admin_id uuid; other_id uuid;
 team_a uuid; team_b uuid; public_id uuid; private_id uuid;
 denied boolean; changed integer; result jsonb;
begin
 select p.id into member_id from public.profiles p join auth.users u on u.id=p.id where p.role='member' and u.deleted_at is null and not u.is_anonymous order by p.id limit 1;
 select p.id into other_id from public.profiles p join auth.users u on u.id=p.id where p.role='member' and p.id<>member_id and u.deleted_at is null and not u.is_anonymous order by p.id limit 1;
 select p.id into external_id from public.profiles p join auth.users u on u.id=p.id where p.role='external' and u.deleted_at is null and not u.is_anonymous order by p.id limit 1;
 select p.id into admin_id from public.profiles p join auth.users u on u.id=p.id where p.role='admin' and u.deleted_at is null and not u.is_anonymous order by p.id limit 1;
 assert member_id is not null and other_id is not null and external_id is not null and admin_id is not null, 'Existing four-role identities required';
 begin
  insert into startup_radar.teams(name) values('[ROLLBACK TEST] A') returning id into team_a;
  insert into startup_radar.teams(name) values('[ROLLBACK TEST] B') returning id into team_b;
  insert into startup_radar.team_members(team_id,user_id,role) values(team_a,member_id,'OWNER'),(team_a,external_id,'MEMBER'),(team_b,other_id,'OWNER');
  insert into startup_radar.team_profiles(team_id,profile) values(team_a,'{"preset":0}'),(team_b,'{"business_status":"CORPORATION"}');
  perform set_config('request.jwt.claim.sub',admin_id::text,true);
  set local role authenticated;
  insert into public.gfc_notices(title,body,state,published_at) values('[ROLLBACK TEST] Public','Synthetic only','PUBLISHED',now()) returning id into public_id;
  insert into public.gfc_notices(title,body,state,published_at,visibility) values('[ROLLBACK TEST] Private','Synthetic only','PUBLISHED',now(),'MEMBERS_ONLY') returning id into private_id;
  update public.gfc_notices set is_pinned=true where id=public_id;
  assert (select revision=2 from public.gfc_notices where id=public_id), 'Admin revision/pin failed';
  reset role;
  assert (select created_by=admin_id from public.gfc_notices where id=public_id), 'Creator audit missing';
  perform set_config('request.jwt.claim.sub','',true);
  set local role anon;
  assert (select count(*)=1 from public.gfc_notices where id in (public_id,private_id)), 'Anonymous notice visibility';
  denied:=false;
  begin perform count(*) from startup_radar.programs; exception when insufficient_privilege then denied:=true; end;
  assert denied, 'Anonymous Radar access';
  reset role;
  perform set_config('request.jwt.claim.sub',external_id::text,true);
  set local role authenticated;
  assert (select count(*)=1 from public.gfc_notices where id in (public_id,private_id)), 'External notice visibility';
  assert (select count(*)=0 from startup_radar.programs), 'External Radar title/count leak';
  assert (select count(*)=0 from startup_radar.team_profiles where team_id in (team_a,team_b)), 'Stray Radar membership bypass';
  denied:=false;
  begin update public.profiles set role='admin' where id=external_id; exception when insufficient_privilege then denied:=true; end;
  assert denied, 'GFC role escalation';
  reset role;
  perform set_config('request.jwt.claim.sub',member_id::text,true);
  set local role authenticated;
  assert (select count(*)=2 from public.gfc_notices where id in (public_id,private_id)), 'Member notices';
  assert (select count(*)>0 from startup_radar.programs), 'Member real Radar read';
  assert (select count(*)=1 from startup_radar.team_profiles where team_id in (team_a,team_b)), 'Cross-team profile leak';
  update startup_radar.team_profiles set profile='{}' where team_id=team_b;
  get diagnostics changed=row_count; assert changed=0, 'Cross-team write';
  denied:=false;
  begin insert into public.gfc_notices(title,body) values('Forbidden','Forbidden'); exception when insufficient_privilege then denied:=true; end;
  assert denied, 'Member notice write';
  insert into startup_radar.team_notification_preferences(team_id,enabled) values(team_a,false);
  assert (select not enabled from startup_radar.team_notification_preferences where team_id=team_a), 'Preferences without channel';
  reset role;
  perform set_config('request.jwt.claim.sub',admin_id::text,true);
  set local role authenticated;
  update public.gfc_notices set state='ARCHIVED' where id=public_id;
  reset role;
  set local role anon;
  assert (select count(*)=0 from public.gfc_notices where id in (public_id,private_id)), 'Archive visibility';
  reset role;
  result=jsonb_build_object('status','PASS','synthetic_rows_rolled_back',true,'auth_profiles_modified',false,
    'checks',jsonb_build_array('anonymous public-only notices','anonymous Radar denied','external public-only notices',
    'external Radar titles/counts denied','stray Radar membership cannot bypass GFC role','GFC role escalation denied',
    'member public and member notices','member reads actual Radar program','cross-team private profile read/write denied',
    'member notice write denied','admin create/publish/pin/revision/archive','creator audit','preferences before Telegram link'));
  raise exception using errcode='ZX001',message='Intentional rollback of synthetic integration fixtures';
 exception when sqlstate 'ZX001' then null;
 end;
 assert not exists(select 1 from public.gfc_notices where id in (public_id,private_id)), 'Notice fixture rollback failed';
 assert not exists(select 1 from startup_radar.teams where id in (team_a,team_b)), 'Team fixture rollback failed';
 insert into pg_temp.gfc_notice_verification values(result);
end $test$;
select payload from pg_temp.gfc_notice_verification;
