begin;
set local lock_timeout='3s';
set local statement_timeout='30s';

alter table startup_radar.weekly_briefings
 add column publication_kind text not null default 'WEEKLY' check(publication_kind in ('WEEKLY','INITIAL_BASELINE')),
 add column display_start date,
 add column display_end date,
 add column snapshot_date date,
 add constraint briefing_display_window check(
  (display_start is null and display_end is null) or
  (display_start is not null and display_end is not null and display_end=display_start+6)),
 add constraint briefing_baseline_date check((publication_kind='INITIAL_BASELINE')=(snapshot_date is not null));
alter table startup_radar.weekly_briefings drop constraint weekly_briefings_week_start_key;
alter table startup_radar.weekly_briefings add unique(week_start,publication_kind);
create unique index weekly_one_initial_baseline on startup_radar.weekly_briefings(publication_kind)
 where publication_kind='INITIAL_BASELINE';

create function startup_radar.official_calendar_date(value text) returns date
language plpgsql immutable security invoker set search_path='' as $$
begin
 if value ~ '^\d{4}-\d{2}-\d{2}($|[T ])' then return left(value,10)::date; end if;
 if value ~ '^\d{8}$' then
  return (substr(value,1,4)||'-'||substr(value,5,2)||'-'||substr(value,7,2))::date;
 end if;
 return null;
exception when datetime_field_overflow or invalid_datetime_format then return null;
end $$;
revoke all on function startup_radar.official_calendar_date(text) from public,anon,authenticated;
grant execute on function startup_radar.official_calendar_date(text) to service_role;

-- This is an operator-only correction of stored publication rows, never an ingestion path.
create function startup_radar.split_initial_publication(p_id uuid,p_reason text,p_expected_count integer)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare
 original startup_radar.weekly_briefings%rowtype;
 baseline_id uuid;
 prior jsonb;
 evidence jsonb;
 recent_ids uuid[];
 snapshot_day date;
 window_start date;
 window_end date;
 total integer;
 recent integer;
 answer jsonb;
begin
 if p_reason is null or length(trim(p_reason)) not between 5 and 500 or p_expected_count is null or p_expected_count<1 then
  raise exception 'An explicit correction reason and expected snapshot count are required';
 end if;
 perform pg_advisory_xact_lock(782394203);
 select * into original from startup_radar.weekly_briefings where id=p_id for update;
 if not found or original.status<>'PUBLISHED' or original.publication_kind<>'WEEKLY' then
  raise exception 'A published weekly snapshot is required'; end if;
 select detail->'result' into answer from startup_radar.admin_audit
  where action='INITIAL_PUBLICATION_SPLIT' and entity_id=p_id::text order by created_at desc limit 1;
 if answer is not null then return answer||'{"unchanged":true}'::jsonb; end if;
 if exists(select 1 from startup_radar.weekly_briefings where id<>p_id) then
  raise exception 'Only the first publication can establish the initial baseline'; end if;
 if exists(select 1 from startup_radar.weekly_announcements where briefing_id=p_id) then
  raise exception 'An already announced publication cannot be silently split'; end if;
 select count(*),jsonb_agg(to_jsonb(i) order by display_order) into total,prior
  from startup_radar.weekly_briefing_items i where briefing_id=p_id;
 if total<>p_expected_count or total<>original.item_count or original.new_count<>total then
  raise exception 'First snapshot count or NEW-only precondition changed'; end if;
 snapshot_day:=(original.published_at at time zone 'Asia/Seoul')::date;
 window_end:=snapshot_day-1;
 window_start:=window_end-6;
 -- Only official portal publication fields or normalized official application starts.
 -- Observation timestamps constrain provenance to the snapshot; they never establish recency.
 with dates as (
  select i.program_id,
   coalesce((select min(startup_radar.official_calendar_date(s.raw_metadata->>'creatPnttm'))
    from startup_radar.program_source_snapshots s join startup_radar.sources src on src.id=s.source_id
    where s.program_version_id=i.program_version_id and src.adapter='BIZINFO'
      and s.observed_at<=original.published_at),
    case when i.snapshot->>'application_start_precision' in ('DATE','DATETIME')
      then startup_radar.official_calendar_date(i.snapshot->>'application_start_at') end) official_date,
   case when exists(select 1 from startup_radar.program_source_snapshots s
      join startup_radar.sources src on src.id=s.source_id
      where s.program_version_id=i.program_version_id and src.adapter='BIZINFO'
       and s.observed_at<=original.published_at
       and startup_radar.official_calendar_date(s.raw_metadata->>'creatPnttm') is not null)
    then 'BIZINFO_OFFICIAL_PUBLICATION' else 'OFFICIAL_APPLICATION_START_OR_UNKNOWN' end evidence_kind
  from startup_radar.weekly_briefing_items i where i.briefing_id=p_id
 )
 select coalesce(array_agg(program_id) filter(where official_date between window_start and window_end),'{}'::uuid[]),
  jsonb_agg(jsonb_build_object('program_id',program_id,'official_date',official_date,'evidence_kind',evidence_kind,
   'partition',case when official_date between window_start and window_end then 'WEEKLY' else 'INITIAL_BASELINE' end))
 into recent_ids,evidence from dates;
 recent:=cardinality(recent_ids);
 insert into startup_radar.weekly_briefings(
  week_start,week_end,title,status,published_at,item_count,new_count,updated_count,summary,
  collection_status,ingestion_run_id,publication_kind,snapshot_date)
 values(original.week_start,original.week_end,
  'StartupRadar 최초 수집 기준 진행 중 지원사업 목록 ('||to_char(snapshot_day,'MM.DD')||' 기준)',
  'PUBLISHED',original.published_at,total-recent,total-recent,0,
  '아래 목록은 StartupRadar 최초 운영 시점에 이미 모집 중이거나 유효한 지원사업을 정리한 초기 기준 자료입니다. 이후 주간 공지에서는 새로 확인된 사업과 주요 변경사항을 중심으로 안내합니다.',
  original.collection_status,original.ingestion_run_id,'INITIAL_BASELINE',snapshot_day)
 returning id into baseline_id;
 update startup_radar.weekly_briefing_items set briefing_id=baseline_id
  where briefing_id=p_id and not(program_id=any(recent_ids));
 -- Original display positions preserve the existing deadline order in both partitions.
 update startup_radar.weekly_briefings set
  title=to_char(window_start,'MM.DD')||' ~ '||to_char(window_end,'MM.DD')||' 주간 지원사업 공지',
  item_count=recent,new_count=recent,updated_count=0,
  summary='공식 공고 등록일 또는 모집 시작일이 '||to_char(window_start,'MM.DD')||' ~ '||to_char(window_end,'MM.DD')||
   '인 지원사업 '||recent||'건입니다.',
  display_start=window_start,display_end=window_end,revision=revision+1,updated_at=now()
  where id=p_id;
 answer:=jsonb_build_object('weekly_id',p_id,'baseline_id',baseline_id,'snapshot_date',snapshot_day,
  'window_start',window_start,'window_end',window_end,'weekly_count',recent,'baseline_count',total-recent,
  'total',total,'overlap',0,'revision',original.revision+1);
 insert into startup_radar.admin_audit(action,entity_id,detail)
 values('INITIAL_PUBLICATION_SPLIT',p_id::text,jsonb_build_object('reason',trim(p_reason),
  'previous_briefing',to_jsonb(original),'previous_items',prior,'classification',evidence,'result',answer,
  'actor','PRIVILEGED_PUBLICATION_OPERATOR','telegram_sent',false));
 return answer;
end $$;
revoke all on function startup_radar.split_initial_publication(uuid,text,integer) from public,anon,authenticated;
grant execute on function startup_radar.split_initial_publication(uuid,text,integer) to service_role;

create or replace function public.gfc_radar_weekly_briefings(p_limit integer default 20,p_offset integer default 0,p_q text default '')
returns jsonb language plpgsql stable security invoker set search_path='' as $$
declare result jsonb;
begin
 if auth.uid() is null or coalesce(public.my_role(),'') not in ('member','admin') then
  raise exception using errcode='42501',message='Verified GFC membership required'; end if;
 if p_limit is null or p_limit not between 1 and 50 or p_offset is null or p_offset<0 or length(p_q)>200 then
  raise exception using errcode='22023',message='Invalid pagination'; end if;
 select jsonb_build_object('items',coalesce(jsonb_agg(to_jsonb(x) order by x.week_start desc,x.publication_kind desc,x.id),'[]')) into result from (
  select id,week_start,week_end,title,published_at,item_count,new_count,updated_count,summary,revision,
   publication_kind,display_start,display_end,snapshot_date
  from startup_radar.weekly_briefings where status='PUBLISHED' and title ilike '%'||coalesce(p_q,'')||'%'
  order by week_start desc,publication_kind desc,id limit p_limit offset p_offset
 ) x;
 return result || jsonb_build_object('total',(select count(*) from startup_radar.weekly_briefings
  where status='PUBLISHED' and title ilike '%'||coalesce(p_q,'')||'%'));
end $$;
create or replace function public.gfc_radar_weekly_briefing(p_id uuid)
returns jsonb language plpgsql stable security invoker set search_path='' as $$
declare result jsonb;
begin
 if auth.uid() is null or coalesce(public.my_role(),'') not in ('member','admin') then
  raise exception using errcode='42501',message='Verified GFC membership required'; end if;
 select jsonb_build_object('id',b.id,'week_start',b.week_start,'week_end',b.week_end,'title',b.title,
  'published_at',b.published_at,'item_count',b.item_count,'new_count',b.new_count,'updated_count',b.updated_count,
  'publication_kind',b.publication_kind,'display_start',b.display_start,'display_end',b.display_end,'snapshot_date',b.snapshot_date,
  'summary',b.summary,'revision',b.revision,'items',coalesce((select jsonb_agg(
    jsonb_build_object('change_type',i.change_type,'facts',i.snapshot) order by i.display_order)
    from startup_radar.weekly_briefing_items i where i.briefing_id=b.id),'[]')) into result
  from startup_radar.weekly_briefings b where b.id=p_id and b.status='PUBLISHED';
 return result;
end $$;
comment on table startup_radar.weekly_briefings is 'One weekly publication per operational Seoul week, plus at most one initial baseline archive. Both establish known program history.';
notify pgrst,'reload schema';
commit;
