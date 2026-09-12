-- Synthetic GFC membership fixture, NEVER a production migration.
-- Legacy tests explicitly create synthetic member identities. Tests can override
-- roles to external/admin. Real GFC uses the protected public.profiles table.
create table public.test_gfc_roles(user_id uuid primary key references auth.users on delete cascade, role text not null);
create function public.my_role() returns text language plpgsql stable security definer set search_path='' as $$
declare r text; begin
 if not exists(select 1 from auth.users where id=auth.uid()) then return null; end if;
 select role into r from public.test_gfc_roles where user_id=auth.uid();
 if r is not null then return r; end if;
 if exists(select 1 from startup_radar.admin_users where user_id=auth.uid()) then return 'admin'; end if;
 return 'member';
end $$;
revoke execute on function public.my_role() from public,anon;
grant execute on function public.my_role() to authenticated;
