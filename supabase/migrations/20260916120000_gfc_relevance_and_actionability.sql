begin;
set local lock_timeout='3s';
set local statement_timeout='60s';

-- GFC Relevance v1.1.
-- Kept in its own table, keyed by the immutable program version, so that an
-- editorial judgement never enters the material fingerprint that drives
-- NEW/UPDATE detection. Re-versioning the classifier therefore cannot make
-- every stored program look materially changed.
create table startup_radar.program_relevance (
 program_version_id uuid not null references startup_radar.program_versions on delete cascade,
 relevance_version text not null,
 relevance_status text not null check(relevance_status in ('GFC_RELEVANT','CONDITIONAL','OUT_OF_SCOPE','REVIEW_REQUIRED')),
 startup_leverage text not null check(startup_leverage in ('HIGH','LOW','UNKNOWN')),
 applicability text not null check(applicability in ('BROAD','RESTRICTED','UNKNOWN')),
 startup_leverage_reason text,
 restriction_summary text,
 classification_method text not null,
 confidence numeric check(confidence is null or confidence between 0 and 1),
 evidence jsonb not null default '{}'::jsonb check(jsonb_typeof(evidence)='object'),
 classified_at timestamptz not null default now(),
 primary key(program_version_id,relevance_version),
 -- REVIEW_REQUIRED is an operational triage state, never a member-facing class.
 check((relevance_status='GFC_RELEVANT')=(startup_leverage='HIGH' and applicability='BROAD')),
 check((relevance_status='CONDITIONAL')=(startup_leverage='HIGH' and applicability='RESTRICTED'))
);
create index program_relevance_status_idx on startup_radar.program_relevance(relevance_version,relevance_status);
alter table startup_radar.program_relevance enable row level security;
revoke all on startup_radar.program_relevance from public,anon,authenticated;
grant all on startup_radar.program_relevance to service_role;
comment on table startup_radar.program_relevance is
 'GFC relevance classification per program version. Deliberately outside weekly.MATERIAL so it cannot affect NEW/UPDATE hashes. Operator-only; members see the denormalized publication decision on weekly_briefing_items.';

-- The published editorial decision is denormalized onto the item so an already
-- published article stays stable even if the classifier is later re-run.
alter table startup_radar.weekly_briefing_items
 add column relevance_status text check(relevance_status in ('GFC_RELEVANT','CONDITIONAL')),
 add column restriction_summary text,
 add column relevance_version text,
 add constraint briefing_item_conditional_needs_reason
  check(relevance_status is distinct from 'CONDITIONAL' or restriction_summary is not null);
create index weekly_briefing_items_relevance_idx on startup_radar.weekly_briefing_items(briefing_id,relevance_status);

-- Operator-only correction of an existing published article. It reorders,
-- annotates and withdraws visible items; it never collects sources, never edits
-- programs/versions/provenance, never creates a briefing, and never announces.
create function startup_radar.apply_publication_correction(
 p_id uuid,p_reason text,p_summary text,p_visible jsonb)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare
 original startup_radar.weekly_briefings%rowtype;
 prior jsonb;
 kept integer;
 removed integer;
 fresh integer;
 changed integer;
 answer jsonb;
begin
 if p_reason is null or length(trim(p_reason)) not between 5 and 500 then
  raise exception 'An explicit correction reason is required'; end if;
 if p_visible is null or jsonb_typeof(p_visible)<>'array' then
  raise exception 'A visible-item array is required'; end if;
 perform pg_advisory_xact_lock(782394203);
 select * into original from startup_radar.weekly_briefings where id=p_id for update;
 if not found or original.status<>'PUBLISHED' then
  raise exception 'A published briefing is required'; end if;

 select count(*),jsonb_agg(to_jsonb(i) order by i.display_order) into removed,prior
  from startup_radar.weekly_briefing_items i where i.briefing_id=p_id;

 create temporary table _correction(
  program_id uuid primary key,display_order integer not null,
  relevance_status text not null,restriction_summary text,relevance_version text not null) on commit drop;
 insert into _correction(program_id,display_order,relevance_status,restriction_summary,relevance_version)
 select (value->>'program_id')::uuid,(value->>'display_order')::integer,
        value->>'relevance_status',nullif(value->>'restriction_summary',''),value->>'relevance_version'
 from jsonb_array_elements(p_visible);

 if exists(select 1 from _correction c where c.relevance_status not in ('GFC_RELEVANT','CONDITIONAL')) then
  raise exception 'Only GFC_RELEVANT or CONDITIONAL items may stay visible'; end if;
 if exists(select 1 from _correction c where c.relevance_status='CONDITIONAL' and c.restriction_summary is null) then
  raise exception 'A CONDITIONAL item requires its restriction summary'; end if;
 if exists(select 1 from _correction c where not exists(
    select 1 from startup_radar.weekly_briefing_items i where i.briefing_id=p_id and i.program_id=c.program_id)) then
  raise exception 'Correction may only retain items already published in this briefing'; end if;

 -- Preserve the withdrawn snapshots before anything is removed.
 insert into startup_radar.admin_audit(action,entity_id,detail)
 values('WEEKLY_PUBLICATION_CORRECTION',p_id::text,jsonb_build_object(
  'reason',trim(p_reason),'previous_briefing',to_jsonb(original),'previous_items',prior,
  'retained',(select coalesce(jsonb_agg(to_jsonb(c) order by c.display_order),'[]') from _correction c),
  'actor','PRIVILEGED_PUBLICATION_OPERATOR','telegram_sent',false));

 delete from startup_radar.weekly_briefing_items i
  where i.briefing_id=p_id and not exists(select 1 from _correction c where c.program_id=i.program_id);
 -- Two steps: display_order is unique per briefing, so renumber out of the way first.
 update startup_radar.weekly_briefing_items set display_order=display_order+100000 where briefing_id=p_id;
 update startup_radar.weekly_briefing_items i set display_order=c.display_order,
  relevance_status=c.relevance_status,restriction_summary=c.restriction_summary,
  relevance_version=c.relevance_version
  from _correction c where i.briefing_id=p_id and i.program_id=c.program_id;

 select count(*),count(*) filter(where change_type='NEW'),count(*) filter(where change_type='UPDATE')
  into kept,fresh,changed from startup_radar.weekly_briefing_items where briefing_id=p_id;
 removed:=removed-kept;

 -- Identity, first publication time and the display window are preserved.
 update startup_radar.weekly_briefings set
  item_count=kept,new_count=fresh,updated_count=changed,summary=p_summary,
  revision=revision+1,updated_at=now() where id=p_id;

 answer:=jsonb_build_object('briefing_id',p_id,'publication_kind',original.publication_kind,
  'retained',kept,'withdrawn',removed,'new_count',fresh,'updated_count',changed,
  'revision',original.revision+1,'published_at',original.published_at);
 insert into startup_radar.admin_audit(action,entity_id,detail)
 values('WEEKLY_PUBLICATION_CORRECTION_RESULT',p_id::text,jsonb_build_object('result',answer,'telegram_sent',false));
 return answer;
end $$;
revoke all on function startup_radar.apply_publication_correction(uuid,text,text,jsonb) from public,anon,authenticated;
grant execute on function startup_radar.apply_publication_correction(uuid,text,text,jsonb) to service_role;

-- Member-facing contract: the publication decision and the key restriction only.
-- Classifier internals, evidence, leverage axes and source errors stay private.
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
    jsonb_build_object('change_type',i.change_type,'facts',i.snapshot,
     'relevance_status',i.relevance_status,'restriction_summary',i.restriction_summary)
    order by i.display_order)
    from startup_radar.weekly_briefing_items i where i.briefing_id=b.id),'[]')) into result
  from startup_radar.weekly_briefings b where b.id=p_id and b.status='PUBLISHED';
 return result;
end $$;

comment on table startup_radar.weekly_briefing_items is
 'Immutable editorial snapshot per published opportunity, plus the published GFC relevance decision. Only GFC_RELEVANT and CONDITIONAL are ever stored here; OUT_OF_SCOPE and REVIEW_REQUIRED remain in program_relevance.';
notify pgrst,'reload schema';
commit;
