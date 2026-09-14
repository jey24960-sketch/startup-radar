begin;
set local lock_timeout='3s';
set local statement_timeout='30s';

create table startup_radar.weekly_schedule (
 singleton boolean primary key default true check(singleton),
 enabled boolean not null default true,
 weekday integer not null default 1 check(weekday between 0 and 6),
 hour integer not null default 15 check(hour between 0 and 23),
 minute integer not null default 0 check(minute between 0 and 59),
 revision integer not null default 1,
 updated_at timestamptz not null default now()
);
insert into startup_radar.weekly_schedule(singleton) values(true);
create table startup_radar.weekly_schedule_attempts (
 week_start date primary key,
 execution_id uuid not null references startup_radar.worker_executions,
 schedule_revision integer not null,
 attempted_at timestamptz not null default now()
);
alter table startup_radar.weekly_schedule enable row level security;
alter table startup_radar.weekly_schedule_attempts enable row level security;
revoke all on startup_radar.weekly_schedule,startup_radar.weekly_schedule_attempts from public,anon,authenticated;
grant all on startup_radar.weekly_schedule,startup_radar.weekly_schedule_attempts to service_role;
grant select on startup_radar.weekly_schedule to authenticated;
create policy weekly_schedule_admin_read on startup_radar.weekly_schedule for select to authenticated
 using ((select auth.uid()) is not null and (select public.my_role())='admin');

-- Only these narrow, authenticated admin operations can mutate editorial state.
-- No direct client UPDATE privilege on source facts, publications or audit records.
create function startup_radar.save_weekly_schedule(p_enabled boolean,p_weekday integer,p_hour integer,p_minute integer,p_revision integer)
returns jsonb language plpgsql security definer set search_path='' as $$
declare old startup_radar.weekly_schedule; result startup_radar.weekly_schedule;
begin
 if auth.uid() is null or coalesce(public.my_role(),'')<>'admin' then
  raise exception using errcode='42501',message='GFC administrator required'; end if;
 if p_enabled is null or p_weekday is null or p_weekday not between 0 and 6 or p_hour is null or p_hour not between 0 and 23
  or p_minute is null or p_minute not between 0 and 59 or p_revision is null then
  raise exception using errcode='22023',message='Invalid weekly schedule'; end if;
 select * into old from startup_radar.weekly_schedule where singleton for update;
 if old.revision<>p_revision then raise exception using errcode='40001',message='Schedule changed; reload before saving'; end if;
 update startup_radar.weekly_schedule set enabled=p_enabled,weekday=p_weekday,hour=p_hour,minute=p_minute,
  revision=revision+1,updated_at=now() where singleton returning * into result;
 insert into startup_radar.admin_audit(actor_id,action,entity_id,detail)
  values(auth.uid(),'WEEKLY_SCHEDULE_EDIT','weekly',jsonb_build_object('before',to_jsonb(old),'after',to_jsonb(result)));
 return to_jsonb(result);
end $$;

create function startup_radar.edit_weekly_briefing(p_id uuid,p_revision integer,p_title text,p_summary text,p_items jsonb,p_note text)
returns jsonb language plpgsql security definer set search_path='' as $$
declare b startup_radar.weekly_briefings; old_items jsonb; item jsonb; facts jsonb; k text; v text;
 allowed text[]:=array['title','organization','support_summary','applicant_summary','application_end_at','application_end_precision','official_url','application_url'];
begin
 if auth.uid() is null or coalesce(public.my_role(),'')<>'admin' then
  raise exception using errcode='42501',message='GFC administrator required'; end if;
 if p_title is null or length(trim(p_title)) not between 1 and 200 or p_summary is null or length(trim(p_summary)) not between 1 and 4000
  or p_note is null or length(trim(p_note)) not between 5 and 500 or p_revision is null or p_items is null
  or jsonb_typeof(p_items)<>'array' or jsonb_array_length(p_items)>1000 then
  raise exception using errcode='22023',message='Invalid correction fields'; end if;
 select * into b from startup_radar.weekly_briefings where id=p_id and status='PUBLISHED' for update;
 if not found then raise exception using errcode='22023',message='Published briefing not found'; end if;
 if b.revision<>p_revision then raise exception using errcode='40001',message='Briefing changed; reload before saving'; end if;
 if exists(select 1 from startup_radar.weekly_announcements where briefing_id=p_id and state='SENDING') then
  raise exception using errcode='55000',message='Announcement is sending; retry after delivery completes'; end if;
 if exists(select 1 from jsonb_array_elements(p_items) x group by x->>'display_order' having count(*)>1) then
  raise exception using errcode='22023',message='Duplicate item'; end if;
 select coalesce(jsonb_agg(to_jsonb(i) order by display_order),'[]') into old_items
  from startup_radar.weekly_briefing_items i where briefing_id=p_id;
 for item in select * from jsonb_array_elements(p_items) loop
  if jsonb_typeof(item)<>'object' or jsonb_typeof(item->'facts') is distinct from 'object'
   or coalesce(item->>'display_order','') !~ '^[0-9]{1,6}$' then
   raise exception using errcode='22023',message='Invalid item'; end if;
  facts:=item->'facts';
  for k,v in select key,value from jsonb_each_text(facts) loop
   if not k=any(allowed) or (facts->k<>'null'::jsonb and jsonb_typeof(facts->k)<>'string') or length(v)>8000 then
    raise exception using errcode='22023',message='Invalid item field'; end if;
   if k in ('title','organization') and (v is null or length(trim(v)) not between 1 and 500) then
    raise exception using errcode='22023',message='Title and organization required'; end if;
   if k in ('official_url','application_url') and v is not null and
    (length(v)>2000 or v !~ '^https?://[^/@[:space:]<>"\\]+([/][^[:space:]<>"\\]*)?$') then
    raise exception using errcode='22023',message='Invalid public link'; end if;
   if k='official_url' and v is null then raise exception using errcode='22023',message='Official link required'; end if;
   if k='application_end_at' and v is not null then
    if v !~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$' then
     raise exception using errcode='22023',message='Deadline requires timezone'; end if;
    perform v::timestamptz;
   end if;
   if k='application_end_precision' and (v is null or v not in ('UNKNOWN','DATE','DATETIME')) then
    raise exception using errcode='22023',message='Invalid deadline precision'; end if;
  end loop;
  if facts ? 'application_end_at' and not facts ? 'application_end_precision' then
   raise exception using errcode='22023',message='Deadline precision required'; end if;
  if facts ? 'application_end_at' and ((facts->>'application_end_at' is null)<>(facts->>'application_end_precision'='UNKNOWN')) then
   raise exception using errcode='22023',message='Deadline and precision mismatch'; end if;
  update startup_radar.weekly_briefing_items set snapshot=snapshot||facts
   where briefing_id=p_id and display_order=(item->>'display_order')::integer;
  if not found then raise exception using errcode='22023',message='Unknown briefing item'; end if;
 end loop;
 update startup_radar.weekly_briefings set title=trim(p_title),summary=trim(p_summary),revision=revision+1,updated_at=now() where id=p_id;
 insert into startup_radar.admin_audit(actor_id,action,entity_id,detail) values(auth.uid(),'WEEKLY_EDITORIAL_CORRECTION',p_id::text,
  jsonb_build_object('reason',trim(p_note),'before',to_jsonb(b),'items_before',old_items,
   'after',jsonb_build_object('title',trim(p_title),'summary',trim(p_summary),'patches',p_items,'revision',b.revision+1)));
 return jsonb_build_object('id',p_id,'revision',b.revision+1);
end $$;

create function public.gfc_radar_weekly_schedule() returns jsonb language plpgsql stable security invoker set search_path='' as $$
begin
 if auth.uid() is null or coalesce(public.my_role(),'')<>'admin' then
  raise exception using errcode='42501',message='GFC administrator required'; end if;
 return (select to_jsonb(s)||jsonb_build_object('timezone','Asia/Seoul') from startup_radar.weekly_schedule s where singleton);
end $$;
create function public.gfc_radar_save_weekly_schedule(p_enabled boolean,p_weekday integer,p_hour integer,p_minute integer,p_revision integer)
returns jsonb language sql security invoker set search_path='' as $$
 select startup_radar.save_weekly_schedule(p_enabled,p_weekday,p_hour,p_minute,p_revision)
$$;
create function public.gfc_radar_edit_weekly_briefing(p_id uuid,p_revision integer,p_title text,p_summary text,p_items jsonb,p_note text)
returns jsonb language sql security invoker set search_path='' as $$
 select startup_radar.edit_weekly_briefing(p_id,p_revision,p_title,p_summary,p_items,p_note)
$$;
revoke all on function startup_radar.save_weekly_schedule(boolean,integer,integer,integer,integer),
 startup_radar.edit_weekly_briefing(uuid,integer,text,text,jsonb,text),public.gfc_radar_weekly_schedule(),
 public.gfc_radar_save_weekly_schedule(boolean,integer,integer,integer,integer),
 public.gfc_radar_edit_weekly_briefing(uuid,integer,text,text,jsonb,text) from public,anon,authenticated,service_role;
grant execute on function startup_radar.save_weekly_schedule(boolean,integer,integer,integer,integer),
 startup_radar.edit_weekly_briefing(uuid,integer,text,text,jsonb,text),public.gfc_radar_weekly_schedule(),
 public.gfc_radar_save_weekly_schedule(boolean,integer,integer,integer,integer),
 public.gfc_radar_edit_weekly_briefing(uuid,integer,text,text,jsonb,text) to authenticated;
notify pgrst,'reload schema';
commit;
