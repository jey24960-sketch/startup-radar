begin;
set local lock_timeout = '3s';
set local statement_timeout = '30s';

-- Narrow public API over private-schema tables. No new table grants, RLS
-- changes, role switching, auth writes, or SECURITY DEFINER privileges.
create function public.gfc_radar_me()
returns jsonb language plpgsql stable security invoker set search_path = ''
as $$
declare
  current_user_id uuid := auth.uid();
  gfc_role text := public.my_role();
  member_teams jsonb;
begin
  if current_user_id is null or gfc_role is null or gfc_role not in ('member','admin') then
    raise exception using errcode = '42501', message = 'Verified GFC membership required';
  end if;
  select coalesce(jsonb_agg(jsonb_build_object(
    'id', t.id, 'name', t.name, 'role', m.role,
    'profile', p.profile, 'version', p.version
  ) order by t.created_at,t.id), '[]'::jsonb) into member_teams
  from startup_radar.teams t
  join startup_radar.team_members m on m.team_id=t.id
  join startup_radar.team_profiles p on p.team_id=t.id
  where m.user_id=current_user_id;
  return jsonb_build_object('user_id',current_user_id,'is_admin',gfc_role='admin','teams',member_teams);
end;
$$;
revoke all on function public.gfc_radar_me() from public,anon,authenticated,service_role;
grant execute on function public.gfc_radar_me() to authenticated;
comment on function public.gfc_radar_me() is
  'GFC member context. SECURITY INVOKER; existing member/team RLS applies. No Telegram or operational metadata.';
notify pgrst, 'reload schema';
commit;
