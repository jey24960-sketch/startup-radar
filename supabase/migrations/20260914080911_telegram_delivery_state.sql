begin;
set local lock_timeout='3s';
set local statement_timeout='30s';

-- Existing subscription enabled/individual flags are administrative gates.
-- Member preferences never write them. Unverified channels fail closed.
alter table startup_radar.telegram_subscriptions
 add column channel_health text not null default 'UNVERIFIED' check(channel_health in ('UNVERIFIED','HEALTHY','BLOCKED')),
 add column health_checked_at timestamptz,
 add column health_reason text;
comment on column startup_radar.telegram_subscriptions.enabled is 'Administrative allow gate. False means suspended; member preferences are stored separately.';
comment on column startup_radar.telegram_subscriptions.channel_health is 'Last verified channel state; HEALTHY requires a delivery receipt or explicit documented operator verification.';

-- Preserve existing receipt evidence without activating any subscription.
update startup_radar.telegram_subscriptions s set channel_health='HEALTHY',health_checked_at=x.delivered_at,health_reason='PRIOR_DELIVERY_RECEIPT'
from (
 select distinct on(subscription_id) subscription_id,state,delivered_at,created_at
 from startup_radar.notification_batches order by subscription_id,created_at desc,id desc
) x where x.subscription_id=s.id and x.state='DELIVERED' and x.delivered_at>=now()-interval '30 days';

create function startup_radar.channel_deliverable(admin_enabled boolean,health text,user_enabled boolean)
returns boolean language sql immutable security invoker set search_path='' as $$
 select admin_enabled is true and (health='HEALTHY') is true and coalesce(user_enabled,true);
$$;
revoke all on function startup_radar.channel_deliverable(boolean,text,boolean) from public,anon,authenticated,service_role;
grant execute on function startup_radar.channel_deliverable(boolean,text,boolean) to authenticated,service_role;

create or replace function startup_radar.member_preferences(p_team_id uuid,p_changes jsonb default null)
returns jsonb language plpgsql volatile security definer set search_path='' as $$
declare actor uuid=auth.uid(); membership_role text; preferences jsonb; channels jsonb; prior jsonb; k text; v jsonb;
begin
 if actor is null or coalesce(public.my_role(),'') not in ('member','admin') then raise exception using errcode='42501',message='Verified GFC membership required'; end if;
 select m.role into membership_role from startup_radar.team_members m where m.team_id=p_team_id and m.user_id=actor for share;
 if membership_role is null then raise exception using errcode='42501',message='Team is not accessible'; end if;
 if p_changes is not null then
  if membership_role not in ('OWNER','EDITOR') then raise exception using errcode='42501',message='Team editing requires owner/editor membership'; end if;
  if jsonb_typeof(p_changes)<>'object' or not (p_changes ?& array['enabled','digest_enabled','alerts_enabled','reminders_enabled']) then
   raise exception using errcode='22023',message='All notification flags are required'; end if;
  for k,v in select * from jsonb_each(p_changes) loop
   if k not in ('enabled','digest_enabled','alerts_enabled','reminders_enabled') or jsonb_typeof(v)<>'boolean' then
    raise exception using errcode='22023',message='Invalid notification preference'; end if;
  end loop;
  perform 1 from startup_radar.team_profiles where team_id=p_team_id for update;
  select jsonb_build_object('enabled',p.enabled,'digest_enabled',p.digest_enabled,'alerts_enabled',p.alerts_enabled,'reminders_enabled',p.reminders_enabled)
   into prior from startup_radar.team_notification_preferences p where p.team_id=p_team_id;
  insert into startup_radar.team_notification_preferences(team_id,enabled,digest_enabled,alerts_enabled,reminders_enabled)
   values(p_team_id,(p_changes->>'enabled')::boolean,(p_changes->>'digest_enabled')::boolean,(p_changes->>'alerts_enabled')::boolean,(p_changes->>'reminders_enabled')::boolean)
   on conflict(team_id) do update set enabled=excluded.enabled,digest_enabled=excluded.digest_enabled,alerts_enabled=excluded.alerts_enabled,reminders_enabled=excluded.reminders_enabled;
  insert into startup_radar.admin_audit(actor_id,action,entity_id,detail) values(actor,'TEAM_NOTIFICATION_PREFERENCES',p_team_id::text,jsonb_build_object('before',prior,'after',p_changes,'reason','TEAM_PREFERENCE_SAVE'));
 end if;
 select jsonb_build_object('enabled',p.enabled,'digest_enabled',p.digest_enabled,'alerts_enabled',p.alerts_enabled,'reminders_enabled',p.reminders_enabled)
  into preferences from startup_radar.team_notification_preferences p where p.team_id=p_team_id;
 preferences=coalesce(preferences,'{"enabled":true,"digest_enabled":true,"alerts_enabled":true,"reminders_enabled":true}');
 select coalesce(jsonb_agg(jsonb_build_object(
  'enabled',s.enabled,'user_enabled',(preferences->>'enabled')::boolean,'admin_suspended',not s.enabled,
  'channel_health',s.channel_health,'health_checked_at',s.health_checked_at,
  'connected',s.channel_health='HEALTHY','delivery_capable',s.channel_health='HEALTHY',
  'deliverable',startup_radar.channel_deliverable(s.enabled,s.channel_health,(preferences->>'enabled')::boolean),
  'digest_enabled',s.digest_enabled and (preferences->>'digest_enabled')::boolean,
  'alerts_enabled',s.alerts_enabled and (preferences->>'alerts_enabled')::boolean,
  'reminders_enabled',s.reminders_enabled and (preferences->>'reminders_enabled')::boolean
 ) order by s.created_at,s.id),'[]') into channels from startup_radar.telegram_subscriptions s where s.team_id=p_team_id;
 return jsonb_build_object('bound',jsonb_array_length(channels)>0,
  'connected',exists(select 1 from jsonb_array_elements(channels) x where x->>'connected'='true'),
  'deliverable',exists(select 1 from jsonb_array_elements(channels) x where x->>'deliverable'='true'),
  'preferences',preferences,'subscriptions',channels,
  'updated',case when p_changes is not null then jsonb_array_length(channels) else null end);
end $$;
notify pgrst,'reload schema';
commit;
