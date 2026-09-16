begin;
set local lock_timeout='3s';
set local statement_timeout='30s';

-- Operator controls for StartupRadar: a DB-backed pause switch, a global
-- visibility mode for published content, and soft withdrawal of published
-- weekly briefings. Nothing here changes how briefings are collected,
-- classified or formatted; it only decides whether the worker may act and who
-- may read what was already published.

-- 1. Runtime state. Both rows are seeded to today's effective behaviour so the
--    deployment itself changes nothing: RUNNING and MEMBERS_ONLY.
insert into startup_radar.runtime_settings(key,value) values
 ('radar_operation','{"enabled":true,"reason":null,"updated_by":null,"updated_at":null,"version":1}'::jsonb),
 ('radar_visibility','{"mode":"MEMBERS_ONLY","reason":null,"updated_by":null,"updated_at":null,"version":1}'::jsonb)
on conflict(key) do nothing;

-- 2. Withdrawal is additive. status/published_at/revision/items/material_hash
--    are untouched so a withdrawn issue stays part of NEW/UPDATE history and
--    can never make its programs look new again.
alter table startup_radar.weekly_briefings
 add column withdrawn_at timestamptz,
 add column withdrawn_by uuid references auth.users on delete set null,
 add column withdrawal_reason text check(withdrawal_reason is null or length(withdrawal_reason) between 1 and 300),
 add constraint weekly_briefing_withdrawal_shape check(withdrawn_at is not null or (withdrawn_by is null and withdrawal_reason is null));
create index weekly_briefings_visible_idx on startup_radar.weekly_briefings(week_start desc)
 where status='PUBLISHED' and withdrawn_at is null;

-- 3. The one authoritative read policy. Every published-content RPC and the
--    member RLS policies call this instead of repeating the rules.
create function startup_radar.visibility_mode() returns text
language sql stable security definer set search_path='' as $$
 -- A missing or malformed row is MEMBERS_ONLY, never PUBLIC.
 select coalesce((select case when value->>'mode' in ('PRIVATE','MEMBERS_ONLY','PUBLIC') then value->>'mode' end
  from startup_radar.runtime_settings where key='radar_visibility'),'MEMBERS_ONLY');
$$;
create function startup_radar.can_view_published_content() returns boolean
language plpgsql stable security definer set search_path='' as $$
declare mode text := startup_radar.visibility_mode(); role text := coalesce(public.my_role(),'');
begin
 if role='admin' then return true; end if;
 if mode='PUBLIC' then return true; end if;
 if mode='MEMBERS_ONLY' then return auth.uid() is not null and role in ('member','admin'); end if;
 return false;
end $$;
create function startup_radar.require_published_read() returns void
language plpgsql stable security definer set search_path='' as $$
begin
 if startup_radar.can_view_published_content() then return; end if;
 if startup_radar.visibility_mode()='PRIVATE' then
  raise exception using errcode='42501',message='StartupRadar content is private';
 end if;
 raise exception using errcode='42501',message='Verified GFC membership required';
end $$;
revoke all on function startup_radar.visibility_mode(),startup_radar.can_view_published_content(),startup_radar.require_published_read() from public,anon,authenticated;
grant execute on function startup_radar.visibility_mode(),startup_radar.can_view_published_content(),startup_radar.require_published_read() to authenticated,service_role;

-- Member RLS keeps the same policy so a direct table read can never see more
-- than the RPCs do.
drop policy weekly_member_read on startup_radar.weekly_briefings;
drop policy weekly_item_member_read on startup_radar.weekly_briefing_items;
create policy weekly_member_read on startup_radar.weekly_briefings for select to authenticated
 using (status='PUBLISHED' and withdrawn_at is null and (select startup_radar.can_view_published_content()));
create policy weekly_item_member_read on startup_radar.weekly_briefing_items for select to authenticated
 using ((select startup_radar.can_view_published_content())
 and exists(select 1 from startup_radar.weekly_briefings b where b.id=briefing_id and b.status='PUBLISHED' and b.withdrawn_at is null));

-- 4. Public policy probe: only the mode and whether THIS caller may read. It
--    carries no content and no identity, so anonymous visitors may call it to
--    render the right locked/unavailable state.
create function public.gfc_radar_visibility() returns jsonb
language sql stable security definer set search_path='' as $$
 select jsonb_build_object('mode',startup_radar.visibility_mode(),'can_view',startup_radar.can_view_published_content());
$$;
revoke all on function public.gfc_radar_visibility() from public;
grant execute on function public.gfc_radar_visibility() to anon,authenticated,service_role;

-- 5. Published reads become SECURITY DEFINER behind the central check, so
--    PUBLIC mode never needs anon table grants on startup_radar.*. Withdrawn
--    issues are excluded here and in the detail read. The shape of the result
--    is unchanged from the previous definitions.
create or replace function public.gfc_radar_weekly_briefings(p_limit integer default 20,p_offset integer default 0,p_q text default '')
returns jsonb language plpgsql stable security definer set search_path='' as $$
declare result jsonb;
begin
 perform startup_radar.require_published_read();
 if p_limit is null or p_limit not between 1 and 50 or p_offset is null or p_offset<0 or length(p_q)>200 then
  raise exception using errcode='22023',message='Invalid pagination'; end if;
 select jsonb_build_object('items',coalesce(jsonb_agg(to_jsonb(x) order by x.week_start desc,x.publication_kind desc,x.id),'[]')) into result from (
  select id,week_start,week_end,title,published_at,item_count,new_count,updated_count,summary,revision,
   publication_kind,display_start,display_end,snapshot_date
  from startup_radar.weekly_briefings where status='PUBLISHED' and withdrawn_at is null and title ilike '%'||coalesce(p_q,'')||'%'
  order by week_start desc,publication_kind desc,id limit p_limit offset p_offset
 ) x;
 return result || jsonb_build_object('total',(select count(*) from startup_radar.weekly_briefings
  where status='PUBLISHED' and withdrawn_at is null and title ilike '%'||coalesce(p_q,'')||'%'));
end $$;
create or replace function public.gfc_radar_weekly_briefing(p_id uuid)
returns jsonb language plpgsql stable security definer set search_path='' as $$
declare result jsonb;
begin
 perform startup_radar.require_published_read();
 select jsonb_build_object('id',b.id,'week_start',b.week_start,'week_end',b.week_end,'title',b.title,
  'published_at',b.published_at,'item_count',b.item_count,'new_count',b.new_count,'updated_count',b.updated_count,
  'publication_kind',b.publication_kind,'display_start',b.display_start,'display_end',b.display_end,'snapshot_date',b.snapshot_date,
  'summary',b.summary,'revision',b.revision,'items',coalesce((select jsonb_agg(
    jsonb_build_object('change_type',i.change_type,'facts',i.snapshot,
     'relevance_status',i.relevance_status,'restriction_summary',i.restriction_summary,
     'stage_fit',coalesce((select jsonb_agg(jsonb_build_object('code',c,'label',startup_radar.stage_label(c)) order by o)
                          from unnest(i.stage_codes) with ordinality as s(c,o)),'[]'::jsonb))
    order by i.display_order)
    from startup_radar.weekly_briefing_items i where i.briefing_id=b.id),'[]')) into result
  from startup_radar.weekly_briefings b where b.id=p_id and b.status='PUBLISHED' and b.withdrawn_at is null;
 return result;
end $$;
revoke all on function public.gfc_radar_weekly_briefings(integer,integer,text),public.gfc_radar_weekly_briefing(uuid) from public;
grant execute on function public.gfc_radar_weekly_briefings(integer,integer,text),public.gfc_radar_weekly_briefing(uuid) to anon,authenticated,service_role;

-- 6. Admin controls. Every function rechecks auth.uid() + my_role()='admin',
--    resolves the actor from auth.uid() only, validates input, and writes
--    admin_audit. Settings carry a version for compare-and-set so two
--    operators cannot silently overwrite each other.
create function startup_radar.require_admin() returns uuid
language plpgsql stable security definer set search_path='' as $$
begin
 if auth.uid() is null or coalesce(public.my_role(),'')<>'admin' then
  raise exception using errcode='42501',message='GFC admin required'; end if;
 return auth.uid();
end $$;
revoke all on function startup_radar.require_admin() from public,anon,authenticated;

create function startup_radar.admin_control_snapshot() returns jsonb
language sql stable security definer set search_path='' as $$
 with op as (select value from startup_radar.runtime_settings where key='radar_operation'),
  vis as (select value from startup_radar.runtime_settings where key='radar_visibility'),
  tg as (select value from startup_radar.runtime_settings where key='weekly_telegram_channel')
 select jsonb_build_object(
  'operation',jsonb_build_object('enabled',coalesce((select (value->>'enabled')::boolean from op),true),
   'reason',(select value->>'reason' from op),'updated_at',(select value->>'updated_at' from op),
   'updated_by',(select value->>'updated_by' from op),'version',coalesce((select (value->>'version')::integer from op),1)),
  'visibility',jsonb_build_object('mode',startup_radar.visibility_mode(),
   'reason',(select value->>'reason' from vis),'updated_at',(select value->>'updated_at' from vis),
   'updated_by',(select value->>'updated_by' from vis),'version',coalesce((select (value->>'version')::integer from vis),1)),
  'telegram',jsonb_build_object(
   'configured',coalesce((select nullif(btrim(value->>'chat_id'),'') is not null from tg),false),
   'enabled',coalesce((select (value->>'enabled')::boolean from tg),false),
   'name',coalesce((select nullif(value->>'name','') from tg),'GFC StartupRadar'),
   'join_url',(select nullif(btrim(value->>'join_url'),'') from tg),
   'broadcast_available',coalesce((select (value->>'enabled')::boolean and nullif(btrim(value->>'chat_id'),'') is not null from tg),false)
    and startup_radar.visibility_mode()<>'PRIVATE' and coalesce((select (value->>'enabled')::boolean from op),true)),
  'schedule_gate',jsonb_build_object('name','RADAR_V2_ENABLED','source','github_actions_variable','readable',false,'mutable_from_web',false,
   'schedule','Tuesday 15:00 Asia/Seoul (cron 0 6 * * 2)'),
  'as_of',now());
$$;
revoke all on function startup_radar.admin_control_snapshot() from public,anon,authenticated;

create function public.gfc_radar_admin_control() returns jsonb
language plpgsql stable security definer set search_path='' as $$
begin
 perform startup_radar.require_admin();
 return startup_radar.admin_control_snapshot();
end $$;

create function public.gfc_radar_admin_set_operation(p_enabled boolean,p_expected_version integer,p_reason text default null)
returns jsonb language plpgsql volatile security definer set search_path='' as $$
declare actor uuid := startup_radar.require_admin(); before jsonb; after jsonb;
begin
 if p_enabled is null or p_expected_version is null then raise exception using errcode='22023',message='enabled and expected_version are required'; end if;
 if p_reason is not null and length(btrim(p_reason)) not between 1 and 300 then raise exception using errcode='22023',message='reason must be 1..300 characters'; end if;
 select value into before from startup_radar.runtime_settings where key='radar_operation' for update;
 if before is null then before:='{"enabled":true,"reason":null,"updated_by":null,"updated_at":null,"version":1}'::jsonb; end if;
 if coalesce((before->>'version')::integer,1)<>p_expected_version then
  raise exception using errcode='40001',message='Operation state changed by another operator; reload'; end if;
 after:=jsonb_build_object('enabled',p_enabled,'reason',nullif(btrim(coalesce(p_reason,'')),''),'updated_by',actor,'updated_at',now(),
  'version',coalesce((before->>'version')::integer,1)+1);
 insert into startup_radar.runtime_settings(key,value) values('radar_operation',after)
  on conflict(key) do update set value=excluded.value,updated_at=now();
 insert into startup_radar.admin_audit(actor_id,action,entity_id,detail) values(actor,
  case when p_enabled then 'RADAR_OPERATION_RESUMED' else 'RADAR_OPERATION_PAUSED' end,'radar_operation',
  jsonb_build_object('before',before,'after',after,'reason',nullif(btrim(coalesce(p_reason,'')),'')));
 return startup_radar.admin_control_snapshot();
end $$;

create function public.gfc_radar_admin_set_visibility(p_mode text,p_expected_version integer,p_reason text default null)
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
  raise exception using errcode='40001',message='Visibility changed by another operator; reload'; end if;
 after:=jsonb_build_object('mode',p_mode,'reason',nullif(btrim(coalesce(p_reason,'')),''),'updated_by',actor,'updated_at',now(),
  'version',coalesce((before->>'version')::integer,1)+1);
 insert into startup_radar.runtime_settings(key,value) values('radar_visibility',after)
  on conflict(key) do update set value=excluded.value,updated_at=now();
 insert into startup_radar.admin_audit(actor_id,action,entity_id,detail) values(actor,'RADAR_VISIBILITY_CHANGED','radar_visibility',
  jsonb_build_object('before',before,'after',after,'reason',nullif(btrim(coalesce(p_reason,'')),'')));
 return startup_radar.admin_control_snapshot();
end $$;

-- Management list: withdrawn issues stay visible here, with whether the
-- official channel already carried them (a withdrawal never recalls Telegram).
create function public.gfc_radar_admin_briefings(p_limit integer default 50,p_offset integer default 0)
returns jsonb language plpgsql stable security definer set search_path='' as $$
declare result jsonb;
begin
 perform startup_radar.require_admin();
 if p_limit is null or p_limit not between 1 and 100 or p_offset is null or p_offset<0 then
  raise exception using errcode='22023',message='Invalid pagination'; end if;
 select jsonb_build_object('items',coalesce(jsonb_agg(to_jsonb(x) order by x.published_at desc,x.publication_kind desc,x.id),'[]'),
  'total',(select count(*) from startup_radar.weekly_briefings where status='PUBLISHED')) into result from (
  select b.id,b.title,b.publication_kind,b.published_at,b.item_count,b.new_count,b.updated_count,b.revision,b.week_start,b.week_end,
   b.snapshot_date,b.withdrawn_at,b.withdrawn_by,b.withdrawal_reason,
   exists(select 1 from startup_radar.weekly_announcements a where a.briefing_id=b.id and a.state='DELIVERED') as announced
  from startup_radar.weekly_briefings b where b.status='PUBLISHED'
  order by b.published_at desc,b.publication_kind desc,b.id limit p_limit offset p_offset
 ) x;
 return result;
end $$;

create function public.gfc_radar_admin_withdraw_briefing(p_id uuid,p_reason text default null)
returns jsonb language plpgsql volatile security definer set search_path='' as $$
declare actor uuid := startup_radar.require_admin(); b startup_radar.weekly_briefings%rowtype;
begin
 if p_id is null then raise exception using errcode='22023',message='briefing id is required'; end if;
 if p_reason is not null and length(btrim(p_reason)) not between 1 and 300 then raise exception using errcode='22023',message='reason must be 1..300 characters'; end if;
 select * into b from startup_radar.weekly_briefings where id=p_id and status='PUBLISHED' for update;
 if b.id is null then raise exception using errcode='P0002',message='Published briefing not found'; end if;
 if b.withdrawn_at is not null then raise exception using errcode='40001',message='Briefing is already withdrawn'; end if;
 update startup_radar.weekly_briefings set withdrawn_at=now(),withdrawn_by=actor,withdrawal_reason=nullif(btrim(coalesce(p_reason,'')),'')
  where id=p_id;
 insert into startup_radar.admin_audit(actor_id,action,entity_id,detail) values(actor,'WEEKLY_BRIEFING_WITHDRAWN',p_id::text,
  jsonb_build_object('title',b.title,'publication_kind',b.publication_kind,'revision',b.revision,'published_at',b.published_at,
   'item_count',b.item_count,'reason',nullif(btrim(coalesce(p_reason,'')),''),
   'announced',exists(select 1 from startup_radar.weekly_announcements a where a.briefing_id=p_id and a.state='DELIVERED')));
 return public.gfc_radar_admin_briefings(100,0);
end $$;

create function public.gfc_radar_admin_restore_briefing(p_id uuid)
returns jsonb language plpgsql volatile security definer set search_path='' as $$
declare actor uuid := startup_radar.require_admin(); b startup_radar.weekly_briefings%rowtype;
begin
 if p_id is null then raise exception using errcode='22023',message='briefing id is required'; end if;
 select * into b from startup_radar.weekly_briefings where id=p_id and status='PUBLISHED' for update;
 if b.id is null then raise exception using errcode='P0002',message='Published briefing not found'; end if;
 if b.withdrawn_at is null then raise exception using errcode='40001',message='Briefing is not withdrawn'; end if;
 update startup_radar.weekly_briefings set withdrawn_at=null,withdrawn_by=null,withdrawal_reason=null where id=p_id;
 insert into startup_radar.admin_audit(actor_id,action,entity_id,detail) values(actor,'WEEKLY_BRIEFING_RESTORED',p_id::text,
  jsonb_build_object('title',b.title,'publication_kind',b.publication_kind,'revision',b.revision,'published_at',b.published_at,
   'withdrawn_at',b.withdrawn_at,'withdrawal_reason',b.withdrawal_reason));
 return public.gfc_radar_admin_briefings(100,0);
end $$;

revoke all on function public.gfc_radar_admin_control(),public.gfc_radar_admin_set_operation(boolean,integer,text),
 public.gfc_radar_admin_set_visibility(text,integer,text),public.gfc_radar_admin_briefings(integer,integer),
 public.gfc_radar_admin_withdraw_briefing(uuid,text),public.gfc_radar_admin_restore_briefing(uuid) from public,anon;
grant execute on function public.gfc_radar_admin_control(),public.gfc_radar_admin_set_operation(boolean,integer,text),
 public.gfc_radar_admin_set_visibility(text,integer,text),public.gfc_radar_admin_briefings(integer,integer),
 public.gfc_radar_admin_withdraw_briefing(uuid,text),public.gfc_radar_admin_restore_briefing(uuid) to authenticated,service_role;

comment on column startup_radar.weekly_briefings.withdrawn_at is
 'Soft withdrawal: hidden from every member/public read while set. status, published_at, revision, items and material_hash are never changed by withdrawal or restore.';
comment on function startup_radar.can_view_published_content() is
 'The only visibility rule: admin always; PUBLIC anyone; MEMBERS_ONLY verified member/admin; PRIVATE admin only.';
notify pgrst,'reload schema';
commit;
