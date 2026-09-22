begin;
set local lock_timeout='3s';
set local statement_timeout='30s';

-- Operational week identity and the historical display window remain intact.
-- Only the human-facing title is based on the original Seoul publication day.
create function startup_radar.publication_date_title(p_kind text, p_published_at timestamptz)
returns text language sql immutable strict security invoker set search_path='' as $$
 select extract(month from p_published_at at time zone 'Asia/Seoul')::integer::text || '월 ' ||
        extract(day from p_published_at at time zone 'Asia/Seoul')::integer::text || '일자 ' ||
        case p_kind when 'WEEKLY' then '주간 지원사업 공지'
                    when 'INITIAL_BASELINE' then '최초 지원사업 목록' end
$$;
revoke all on function startup_radar.publication_date_title(text,timestamptz) from public,anon,authenticated,service_role;
grant execute on function startup_radar.publication_date_title(text,timestamptz) to service_role;

-- Also covers older workers and the existing initial-baseline split function.
-- A new publication needs no corrective title audit. Here we audit changes to
-- an existing published title, never modify delivery payloads.
create function startup_radar.normalize_publication_date_title()
returns trigger language plpgsql security invoker set search_path='' as $$
declare normalized text;
begin
 if new.published_at is null then return new; end if;
 normalized := startup_radar.publication_date_title(new.publication_kind,new.published_at);
 if normalized is null then return new; end if;
 new.title := normalized;
 if tg_op='UPDATE' and old.published_at is not null and old.title is distinct from new.title then
  insert into startup_radar.admin_audit(action,entity_id,detail)
  values('WEEKLY_PUBLICATION_TITLE_NORMALIZED',new.id::text,
   jsonb_build_object('before_title',old.title,'after_title',new.title,
    'published_at',new.published_at,'publication_kind',new.publication_kind,
    'reason','Use the first Seoul publication date; preserve operational week and article contents'));
 end if;
 return new;
end $$;
revoke all on function startup_radar.normalize_publication_date_title() from public,anon,authenticated,service_role;
create trigger weekly_publication_date_title
 before insert or update of title,published_at,publication_kind on startup_radar.weekly_briefings
 for each row execute function startup_radar.normalize_publication_date_title();

-- Refuse to guess dates in a drifted production schema. The existing status
-- constraint normally makes this impossible, but the backfill checks directly.
do $$ begin
 if exists(select 1 from startup_radar.weekly_briefings where status='PUBLISHED' and published_at is null) then
  raise exception 'Published briefing without first publication time; inspect before relabeling';
 end if;
end $$;
select pg_advisory_xact_lock(782394203);
update startup_radar.weekly_briefings
 set title=startup_radar.publication_date_title(publication_kind,published_at)
 where published_at is not null
 and title is distinct from startup_radar.publication_date_title(publication_kind,published_at);

-- Deliberately unchanged: IDs, first publication time, week/display/snapshot
-- dates, items, content revision, timestamps, visibility, audit history and the
-- complete announcement ledger (including pending/failed/delivered payloads).
notify pgrst,'reload schema';
commit;
