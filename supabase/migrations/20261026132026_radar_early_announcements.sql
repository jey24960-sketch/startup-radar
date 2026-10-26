begin;
set local lock_timeout='3s';
set local statement_timeout='30s';

-- Internal discovery is not an additional member digest. The existing durable
-- worker owner and operator pause remain authoritative for this new kind.
alter table startup_radar.worker_executions drop constraint worker_executions_kind_check;
alter table startup_radar.worker_executions add constraint worker_executions_kind_check
 check(kind in ('INGEST','DIGEST','REMINDER','HIGH_FIT','TICK','REFRESH','WEEKLY','DISCOVER'));

-- Disabled on deployment. Provision active_from only after a non-delivering
-- baseline import, so old notices cannot be broadcast as rollout exceptions.
insert into startup_radar.runtime_settings(key,value)
 values('early_announcements','{"enabled":false,"active_from":null,"max_items":3,"policy_version":"gfc-early-v1"}'::jsonb)
on conflict(key) do nothing;

create table startup_radar.early_notices (
 id uuid primary key default gen_random_uuid(),
 week_start date not null unique check(extract(isodow from week_start)=1),
 title text not null check(length(title) between 1 and 200),
 summary text not null check(length(summary) between 1 and 1000),
 status text not null default 'PUBLISHED' check(status in ('PUBLISHED','WITHDRAWN')),
 published_at timestamptz not null default now(),
 item_count integer not null check(item_count between 1 and 3),
 withdrawn_at timestamptz,
 withdrawal_reason text check(withdrawal_reason is null or length(withdrawal_reason) between 1 and 300),
 delivery_state text not null default 'PENDING'
   check(delivery_state in ('PENDING','SENDING','DELIVERED','FAILED','UNCERTAIN','EXPIRED')),
 chat_id text,
 payload text,
 attempted_at timestamptz,
 delivered_at timestamptz,
 receipt jsonb,
 failure_reason text,
 check((status='WITHDRAWN')=(withdrawn_at is not null)),
 check(delivery_state not in ('SENDING','DELIVERED','FAILED','UNCERTAIN') or
   (chat_id is not null and payload is not null and attempted_at is not null)),
 check((delivery_state='DELIVERED')=(delivered_at is not null))
);
create table startup_radar.early_notice_items (
 notice_id uuid not null references startup_radar.early_notices(id),
 program_id uuid not null unique references startup_radar.programs(id),
 program_version_id uuid not null references startup_radar.program_versions(id),
 display_order integer not null check(display_order between 0 and 2),
 snapshot jsonb not null,
 stage_codes text[] not null default '{}',
 primary key(notice_id,program_id),
 unique(notice_id,display_order)
);
create index early_notices_visible_idx on startup_radar.early_notices(published_at desc,id)
 where status='PUBLISHED' and withdrawn_at is null;
create index early_notice_items_version_idx on startup_radar.early_notice_items(program_version_id);

-- Fail closed in the database too: a Python policy error must not publish a
-- short-runway or undated exception. Date-only precision is retained as given.
create function startup_radar.require_early_notice_lead() returns trigger
language plpgsql set search_path='' as $$
declare publication timestamptz; deadline timestamptz; starts timestamptz;
begin
 select published_at into publication from startup_radar.early_notices where id=new.notice_id;
 if new.snapshot->>'deadline_type' is distinct from 'FIXED_DATE'
    or coalesce(new.snapshot->>'application_end_precision','UNKNOWN') not in ('DATE','DATETIME')
    or coalesce(new.snapshot->>'application_end_at','')=''
    or new.snapshot->>'application_end_at' !~ '(Z|[+-][0-9]{2}:[0-9]{2})$' then
   raise exception using errcode='23514',message='Verified fixed deadline required for early notice';
 end if;
 begin deadline := (new.snapshot->>'application_end_at')::timestamptz;
 exception when others then
   raise exception using errcode='23514',message='Invalid early notice deadline';
 end;
 if deadline < publication + interval '7 days' then
   raise exception using errcode='23514',message='Early notice requires seven full days before deadline';
 end if;
 if coalesce(new.snapshot->>'application_start_at','')<>'' then
   begin starts := (new.snapshot->>'application_start_at')::timestamptz;
   exception when others then
     raise exception using errcode='23514',message='Invalid early notice application start';
   end;
   if starts>deadline then
     raise exception using errcode='23514',message='Early notice application period is inverted';
   end if;
 end if;
 if not exists(select 1 from startup_radar.program_versions v
               where v.id=new.program_version_id and v.program_id=new.program_id) then
   raise exception using errcode='23514',message='Early notice version does not belong to program';
 end if;
 return new;
end $$;
create trigger early_notice_minimum_lead before insert or update on startup_radar.early_notice_items
 for each row execute function startup_radar.require_early_notice_lead();
revoke all on function startup_radar.require_early_notice_lead() from public,anon,authenticated;

alter table startup_radar.early_notices enable row level security;
alter table startup_radar.early_notice_items enable row level security;
revoke all on startup_radar.early_notices,startup_radar.early_notice_items from public,anon,authenticated;
grant select,insert,update on startup_radar.early_notices,startup_radar.early_notice_items to service_role;
-- No direct member grants: narrow, centrally authorized RPCs expose no channel,
-- payload, send ledger, source metadata or operator-only information.

create function public.gfc_radar_early_notices(p_limit integer default 20,p_offset integer default 0,p_q text default '')
returns jsonb language plpgsql stable security definer set search_path='' as $$
declare result jsonb;
begin
 perform startup_radar.require_published_read();
 if p_limit is null or p_limit not between 1 and 50 or p_offset is null or p_offset<0
    or p_q is null or length(p_q)>200 then
   raise exception using errcode='22023',message='Invalid pagination';
 end if;
 select jsonb_build_object('items',coalesce(jsonb_agg(to_jsonb(x) order by x.published_at desc,x.id),'[]'))
 into result from (
   select id,title,summary,published_at,item_count,'EARLY'::text as publication_kind
   from startup_radar.early_notices
   where status='PUBLISHED' and withdrawn_at is null
     and (p_q='' or title ilike '%'||p_q||'%' or summary ilike '%'||p_q||'%')
   order by published_at desc,id limit p_limit offset p_offset
 ) x;
 return result || jsonb_build_object('total',(
   select count(*) from startup_radar.early_notices
   where status='PUBLISHED' and withdrawn_at is null
     and (p_q='' or title ilike '%'||p_q||'%' or summary ilike '%'||p_q||'%')));
end $$;

create function public.gfc_radar_early_notice(p_id uuid)
returns jsonb language plpgsql stable security definer set search_path='' as $$
declare result jsonb;
begin
 perform startup_radar.require_published_read();
 select jsonb_build_object('id',n.id,'title',n.title,'summary',n.summary,'published_at',n.published_at,
   'item_count',n.item_count,'publication_kind','EARLY',
   'items',coalesce((select jsonb_agg(jsonb_build_object(
      'program_id',i.program_id,'display_order',i.display_order,'change_type','NEW','facts',i.snapshot,
      'relevance_status','GFC_RELEVANT','restriction_summary',null,
      'stage_fit',coalesce((select jsonb_agg(jsonb_build_object('code',code,'label',startup_radar.stage_label(code)) order by ordinal)
         from unnest(i.stage_codes) with ordinality as s(code,ordinal)),'[]'::jsonb)) order by i.display_order,i.program_id)
     from startup_radar.early_notice_items i where i.notice_id=n.id),'[]'::jsonb))
 into result from startup_radar.early_notices n
 where n.id=p_id and n.status='PUBLISHED' and n.withdrawn_at is null;
 return result;
end $$;
revoke all on function public.gfc_radar_early_notices(integer,integer,text),public.gfc_radar_early_notice(uuid) from public;
grant execute on function public.gfc_radar_early_notices(integer,integer,text),public.gfc_radar_early_notice(uuid) to anon,authenticated,service_role;
comment on table startup_radar.early_notices is 'At most one exceptional early announcement per Seoul week. All items have seven full days at publication; ambiguous sends are never automatically retried.';
comment on table startup_radar.early_notice_items is 'Immutable early-publication facts. Each program is announced early at most once, with a verified fixed deadline.';
commit;
