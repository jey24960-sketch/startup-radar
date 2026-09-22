-- Explicit version/state conflicts are permanent business outcomes, not a
-- retryable PostgreSQL serialization failure. PostgREST receives HTTP 409.
-- Existing function identity, ownership, ACL, locks, audit and all data remain.
-- Only four explicit error-code literals change; native serialization errors
-- from PostgreSQL are not caught or remapped.
begin;
set local lock_timeout='3s';
set local statement_timeout='30s';
do $$ begin
 if to_regprocedure('public.gfc_radar_admin_set_operation(boolean,integer,text)') is null
 or to_regprocedure('public.gfc_radar_admin_set_visibility(text,integer,text)') is null
 or to_regprocedure('public.gfc_radar_admin_withdraw_briefing(uuid,text)') is null
 or to_regprocedure('public.gfc_radar_admin_restore_briefing(uuid)') is null then
  raise exception 'Existing Radar operator-control RPCs are required; do not create new default grants';
 end if;
end $$;

create or replace function public.gfc_radar_admin_set_operation(p_enabled boolean,p_expected_version integer,p_reason text default null)
returns jsonb language plpgsql volatile security definer set search_path='' as $$
declare actor uuid := startup_radar.require_admin(); before jsonb; after jsonb;
begin
 if p_enabled is null or p_expected_version is null then raise exception using errcode='22023',message='enabled and expected_version are required'; end if;
 if p_reason is not null and length(btrim(p_reason)) not between 1 and 300 then raise exception using errcode='22023',message='reason must be 1..300 characters'; end if;
 select value into before from startup_radar.runtime_settings where key='radar_operation' for update;
 if before is null then before:='{"enabled":true,"reason":null,"updated_by":null,"updated_at":null,"version":1}'::jsonb; end if;
 if coalesce((before->>'version')::integer,1)<>p_expected_version then
  raise exception using errcode='PT409',message='Operation state changed by another operator; reload'; end if;
 after:=jsonb_build_object('enabled',p_enabled,'reason',nullif(btrim(coalesce(p_reason,'')),''),'updated_by',actor,'updated_at',now(),
  'version',coalesce((before->>'version')::integer,1)+1);
 insert into startup_radar.runtime_settings(key,value) values('radar_operation',after)
  on conflict(key) do update set value=excluded.value,updated_at=now();
 insert into startup_radar.admin_audit(actor_id,action,entity_id,detail) values(actor,
  case when p_enabled then 'RADAR_OPERATION_RESUMED' else 'RADAR_OPERATION_PAUSED' end,'radar_operation',
  jsonb_build_object('before',before,'after',after,'reason',nullif(btrim(coalesce(p_reason,'')),'')));
 return startup_radar.admin_control_snapshot();
end $$;

create or replace function public.gfc_radar_admin_set_visibility(p_mode text,p_expected_version integer,p_reason text default null)
returns jsonb language plpgsql volatile security definer set search_path='' as $$
declare actor uuid := startup_radar.require_admin(); before jsonb; after jsonb;
begin
 if p_mode is null or p_mode not in ('PRIVATE','MEMBERS_ONLY','PUBLIC') then
  raise exception using errcode='22023',message='mode must be PRIVATE, MEMBERS_ONLY or PUBLIC'; end if;
 if p_expected_version is null then raise exception using errcode='22023',message='expected_version is required'; end if;
 if p_reason is not null and length(btrim(p_reason)) not between 1 and 300 then raise exception using errcode='22023',message='reason must be 1..300 characters'; end if;
 select value into before from startup_radar.runtime_settings where key='radar_visibility' for update;
 if before is null then before:='{"mode":"MEMBERS_ONLY","reason":null,"updated_by":null,"updated_at":null,"version":1}'::jsonb; end if;
 if coalesce((before->>'version')::integer,1)<>p_expected_version then
  raise exception using errcode='PT409',message='Visibility changed by another operator; reload'; end if;
 after:=jsonb_build_object('mode',p_mode,'reason',nullif(btrim(coalesce(p_reason,'')),''),'updated_by',actor,'updated_at',now(),
  'version',coalesce((before->>'version')::integer,1)+1);
 insert into startup_radar.runtime_settings(key,value) values('radar_visibility',after)
  on conflict(key) do update set value=excluded.value,updated_at=now();
 insert into startup_radar.admin_audit(actor_id,action,entity_id,detail) values(actor,'RADAR_VISIBILITY_CHANGED','radar_visibility',
  jsonb_build_object('before',before,'after',after,'reason',nullif(btrim(coalesce(p_reason,'')),'')));
 return startup_radar.admin_control_snapshot();
end $$;

create or replace function public.gfc_radar_admin_withdraw_briefing(p_id uuid,p_reason text default null)
returns jsonb language plpgsql volatile security definer set search_path='' as $$
declare actor uuid := startup_radar.require_admin(); b startup_radar.weekly_briefings%rowtype;
begin
 if p_id is null then raise exception using errcode='22023',message='briefing id is required'; end if;
 if p_reason is not null and length(btrim(p_reason)) not between 1 and 300 then raise exception using errcode='22023',message='reason must be 1..300 characters'; end if;
 select * into b from startup_radar.weekly_briefings where id=p_id and status='PUBLISHED' for update;
 if b.id is null then raise exception using errcode='P0002',message='Published briefing not found'; end if;
 if b.withdrawn_at is not null then raise exception using errcode='PT409',message='Briefing is already withdrawn'; end if;
 update startup_radar.weekly_briefings set withdrawn_at=now(),withdrawn_by=actor,withdrawal_reason=nullif(btrim(coalesce(p_reason,'')),'')
  where id=p_id;
 insert into startup_radar.admin_audit(actor_id,action,entity_id,detail) values(actor,'WEEKLY_BRIEFING_WITHDRAWN',p_id::text,
  jsonb_build_object('title',b.title,'publication_kind',b.publication_kind,'revision',b.revision,'published_at',b.published_at,
   'item_count',b.item_count,'reason',nullif(btrim(coalesce(p_reason,'')),''),
   'announced',exists(select 1 from startup_radar.weekly_announcements a where a.briefing_id=p_id and a.state='DELIVERED')));
 return public.gfc_radar_admin_briefings(100,0);
end $$;

create or replace function public.gfc_radar_admin_restore_briefing(p_id uuid)
returns jsonb language plpgsql volatile security definer set search_path='' as $$
declare actor uuid := startup_radar.require_admin(); b startup_radar.weekly_briefings%rowtype;
begin
 if p_id is null then raise exception using errcode='22023',message='briefing id is required'; end if;
 select * into b from startup_radar.weekly_briefings where id=p_id and status='PUBLISHED' for update;
 if b.id is null then raise exception using errcode='P0002',message='Published briefing not found'; end if;
 if b.withdrawn_at is null then raise exception using errcode='PT409',message='Briefing is not withdrawn'; end if;
 update startup_radar.weekly_briefings set withdrawn_at=null,withdrawn_by=null,withdrawal_reason=null where id=p_id;
 insert into startup_radar.admin_audit(actor_id,action,entity_id,detail) values(actor,'WEEKLY_BRIEFING_RESTORED',p_id::text,
  jsonb_build_object('title',b.title,'publication_kind',b.publication_kind,'revision',b.revision,'published_at',b.published_at,
   'withdrawn_at',b.withdrawn_at,'withdrawal_reason',b.withdrawal_reason));
 return public.gfc_radar_admin_briefings(100,0);
end $$;

notify pgrst,'reload schema';
commit;
