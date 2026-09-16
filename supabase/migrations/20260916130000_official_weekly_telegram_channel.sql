begin;
set local lock_timeout='3s';
set local statement_timeout='30s';

-- The normal weekly briefing is one curated publication for every GFC member,
-- so it is announced once, to one official GFC Telegram channel that members
-- join themselves. Team subscriptions and notification preferences remain for
-- advanced alerts and history; they are no longer on the weekly delivery path.

-- Ledger: allow an official-channel target that has no team subscription.
-- (briefing_id, chat_id) stays unique, so one issue can never post twice.
alter table startup_radar.weekly_announcements alter column subscription_id drop not null;
alter table startup_radar.weekly_announcements
 add column target_kind text not null default 'SUBSCRIPTION'
  check(target_kind in ('SUBSCRIPTION','OFFICIAL_CHANNEL')),
 add constraint weekly_announcement_target_shape
  check((target_kind='SUBSCRIPTION')=(subscription_id is not null));

-- Operator-controlled configuration. Disabled until an operator supplies the
-- channel; chat_id is read only by privileged worker code.
insert into startup_radar.runtime_settings(key,value) values
 ('weekly_telegram_channel','{"enabled":false,"chat_id":null,"name":"GFC StartupRadar","join_url":null}'::jsonb)
on conflict(key) do nothing;

-- Member-safe view of the channel. runtime_settings is admin-only under RLS and
-- the row carries chat_id, so this is deliberately SECURITY DEFINER with a
-- membership check and a fixed three-field shape: enabled, name, join_url.
create function public.gfc_radar_telegram_channel()
returns jsonb language plpgsql stable security definer set search_path='' as $$
declare v jsonb; usable boolean; link text;
begin
 if auth.uid() is null or coalesce(public.my_role(),'') not in ('member','admin') then
  raise exception using errcode='42501',message='Verified GFC membership required'; end if;
 select value into v from startup_radar.runtime_settings where key='weekly_telegram_channel';
 usable:=coalesce((v->>'enabled')::boolean,false) and nullif(btrim(v->>'chat_id'),'') is not null;
 link:=case when usable then nullif(btrim(v->>'join_url'),'') end;
 return jsonb_build_object('enabled',link is not null,
  'name',coalesce(nullif(v->>'name',''),'GFC StartupRadar'),'join_url',link);
end $$;
revoke all on function public.gfc_radar_telegram_channel() from public,anon;
grant execute on function public.gfc_radar_telegram_channel() to authenticated,service_role;

comment on column startup_radar.weekly_announcements.target_kind is
 'OFFICIAL_CHANNEL rows carry the weekly briefing to the single GFC channel and have no subscription; SUBSCRIPTION rows are the legacy per-team path.';
notify pgrst,'reload schema';
commit;
