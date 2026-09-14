begin;
set local lock_timeout='3s';
set local statement_timeout='30s';

create table startup_radar.weekly_briefings (
 id uuid primary key default gen_random_uuid(),
 week_start date not null unique check(extract(isodow from week_start)=1),
 week_end date not null check(week_end=week_start+6),
 title text not null, status text not null check(status in ('DRAFT','PUBLISHED')),
 generated_at timestamptz not null default now(), published_at timestamptz,
 item_count integer not null default 0 check(item_count>=0),
 new_count integer not null default 0 check(new_count>=0),
 updated_count integer not null default 0 check(updated_count>=0),
 summary text not null, revision integer not null default 1 check(revision>0),
 collection_status text not null check(collection_status in ('SUCCESS','PARTIAL_SUCCESS')),
 ingestion_run_id uuid not null references startup_radar.ingestion_runs,
 created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
 check(item_count=new_count+updated_count),
 check((status='PUBLISHED')=(published_at is not null))
);
create index weekly_briefings_published_idx on startup_radar.weekly_briefings(week_start desc) where status='PUBLISHED';
create index weekly_briefings_run_idx on startup_radar.weekly_briefings(ingestion_run_id);
create table startup_radar.weekly_briefing_items (
 briefing_id uuid not null references startup_radar.weekly_briefings on delete cascade,
 program_id uuid not null references startup_radar.programs,
 program_version_id uuid not null references startup_radar.program_versions,
 change_type text not null check(change_type in ('NEW','UPDATE')),
 display_order integer not null check(display_order>=0),
 snapshot jsonb not null check(jsonb_typeof(snapshot)='object'),
 material_hash text not null,
 primary key(briefing_id,program_id), unique(briefing_id,display_order)
);
create index weekly_briefing_items_program_idx on startup_radar.weekly_briefing_items(program_id);
create index weekly_briefing_items_version_idx on startup_radar.weekly_briefing_items(program_version_id);
create table startup_radar.weekly_announcements (
 id uuid primary key default gen_random_uuid(),
 briefing_id uuid not null references startup_radar.weekly_briefings,
 subscription_id uuid not null references startup_radar.telegram_subscriptions,
 chat_id text not null, payload text not null,
 state text not null default 'PENDING' check(state in ('PENDING','SENDING','DELIVERED','FAILED','UNCERTAIN','CANCELLED')),
 receipt jsonb, failure_reason text, created_at timestamptz not null default now(),
 attempted_at timestamptz, delivered_at timestamptz,
 unique(briefing_id,chat_id)
);
create index weekly_announcements_subscription_idx on startup_radar.weekly_announcements(subscription_id);
alter table startup_radar.weekly_briefings enable row level security;
alter table startup_radar.weekly_briefing_items enable row level security;
alter table startup_radar.weekly_announcements enable row level security;
revoke all on startup_radar.weekly_briefings,startup_radar.weekly_briefing_items,startup_radar.weekly_announcements from public,anon,authenticated;
grant all on startup_radar.weekly_briefings,startup_radar.weekly_briefing_items,startup_radar.weekly_announcements to service_role;
grant select on startup_radar.weekly_briefings,startup_radar.weekly_briefing_items to authenticated;
create policy weekly_member_read on startup_radar.weekly_briefings for select to authenticated
 using ((select auth.uid()) is not null and (select public.my_role()) in ('member','admin') and status='PUBLISHED');
create policy weekly_item_member_read on startup_radar.weekly_briefing_items for select to authenticated
 using ((select auth.uid()) is not null and (select public.my_role()) in ('member','admin')
 and exists(select 1 from startup_radar.weekly_briefings b where b.id=briefing_id and b.status='PUBLISHED'));

create function public.gfc_radar_weekly_briefings(p_limit integer default 20,p_offset integer default 0,p_q text default '')
returns jsonb language plpgsql stable security invoker set search_path='' as $$
declare result jsonb;
begin
 if auth.uid() is null or coalesce(public.my_role(),'') not in ('member','admin') then
  raise exception using errcode='42501',message='Verified GFC membership required'; end if;
 if p_limit is null or p_limit not between 1 and 50 or p_offset is null or p_offset<0 or length(p_q)>200 then
  raise exception using errcode='22023',message='Invalid pagination'; end if;
 select jsonb_build_object('items',coalesce(jsonb_agg(to_jsonb(x) order by x.week_start desc),'[]')) into result from (
  select id,week_start,week_end,title,published_at,item_count,new_count,updated_count,summary,revision
  from startup_radar.weekly_briefings where status='PUBLISHED' and title ilike '%'||coalesce(p_q,'')||'%'
  order by week_start desc limit p_limit offset p_offset
 ) x;
 return result || jsonb_build_object('total',(select count(*) from startup_radar.weekly_briefings
  where status='PUBLISHED' and title ilike '%'||coalesce(p_q,'')||'%'));
end $$;
create function public.gfc_radar_weekly_briefing(p_id uuid)
returns jsonb language plpgsql stable security invoker set search_path='' as $$
declare result jsonb;
begin
 if auth.uid() is null or coalesce(public.my_role(),'') not in ('member','admin') then
  raise exception using errcode='42501',message='Verified GFC membership required'; end if;
 select jsonb_build_object('id',b.id,'week_start',b.week_start,'week_end',b.week_end,'title',b.title,
  'published_at',b.published_at,'item_count',b.item_count,'new_count',b.new_count,'updated_count',b.updated_count,
  'summary',b.summary,'revision',b.revision,'items',coalesce((select jsonb_agg(
    jsonb_build_object('change_type',i.change_type,'facts',i.snapshot) order by i.display_order)
    from startup_radar.weekly_briefing_items i where i.briefing_id=b.id),'[]')) into result
  from startup_radar.weekly_briefings b where b.id=p_id and b.status='PUBLISHED';
 return result;
end $$;
revoke all on function public.gfc_radar_weekly_briefings(integer,integer,text),public.gfc_radar_weekly_briefing(uuid) from public,anon,authenticated,service_role;
grant execute on function public.gfc_radar_weekly_briefings(integer,integer,text),public.gfc_radar_weekly_briefing(uuid) to authenticated;
alter table startup_radar.worker_executions drop constraint worker_executions_kind_check;
alter table startup_radar.worker_executions add constraint worker_executions_kind_check check(kind in ('INGEST','DIGEST','REMINDER','HIGH_FIT','TICK','REFRESH','WEEKLY'));
comment on table startup_radar.weekly_briefings is 'One immutable published briefing per Seoul Monday-Sunday week. Team calculations and AI are not publication prerequisites.';
notify pgrst,'reload schema';
commit;
