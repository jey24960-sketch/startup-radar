begin;
set local lock_timeout='3s';
set local statement_timeout='60s';

-- User-approved 2026-10-27: startup-related uncertainty is published as a
-- clearly labelled appendix. This does not relax the seven-day date guard or
-- expose unpublished source data, classifier evidence, or operational records.
alter table startup_radar.weekly_briefing_items
 drop constraint weekly_briefing_items_relevance_status_check,
 add constraint weekly_briefing_items_relevance_status_check
  check(relevance_status in ('GFC_RELEVANT','CONDITIONAL','REVIEW_REQUIRED')),
 add constraint briefing_item_review_needs_note
  check(relevance_status is distinct from 'REVIEW_REQUIRED' or
   (coalesce(jsonb_typeof(snapshot->'review_note')='string',false)
    and length(btrim(coalesce(snapshot->>'review_note',''))) between 1 and 1000));

create function startup_radar.enforce_weekly_review_appendix_order()
returns trigger language plpgsql security invoker set search_path='' as $$
begin
 if new.status='PUBLISHED' and exists(
  select 1 from startup_radar.weekly_briefing_items r
  join startup_radar.weekly_briefing_items c on c.briefing_id=r.briefing_id
  where r.briefing_id=new.id and r.relevance_status='REVIEW_REQUIRED'
   and c.relevance_status is distinct from 'REVIEW_REQUIRED'
   and r.display_order<c.display_order) then
  raise exception 'Review-required opportunities must follow confirmed opportunities';
 end if;
 return new;
end $$;
revoke all on function startup_radar.enforce_weekly_review_appendix_order() from public,anon,authenticated;
grant execute on function startup_radar.enforce_weekly_review_appendix_order() to service_role;
create trigger weekly_review_appendix_order_guard before insert or update of status
 on startup_radar.weekly_briefings for each row execute function startup_radar.enforce_weekly_review_appendix_order();

-- Preserve the existing privileged, explicit, retain-only correction operation.
-- Replacing this function does not execute a correction or change old snapshots.
create or replace function startup_radar.apply_publication_correction(
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
  relevance_status text not null,restriction_summary text,relevance_version text not null,
  review_note text) on commit drop;
 insert into _correction(program_id,display_order,relevance_status,restriction_summary,relevance_version,review_note)
 select (value->>'program_id')::uuid,(value->>'display_order')::integer,
        value->>'relevance_status',nullif(value->>'restriction_summary',''),value->>'relevance_version',
        case when jsonb_typeof(value->'review_note')='string' then nullif(btrim(value->>'review_note'),'') end
 from jsonb_array_elements(p_visible);
 if exists(select 1 from _correction c where c.relevance_status not in ('GFC_RELEVANT','CONDITIONAL','REVIEW_REQUIRED')) then
  raise exception 'Only confirmed or explicitly labelled review-required opportunities may stay visible'; end if;
 if exists(select 1 from _correction c where c.relevance_status='CONDITIONAL' and c.restriction_summary is null) then
  raise exception 'A CONDITIONAL item requires its restriction summary'; end if;
 if exists(select 1 from _correction c where not exists(
    select 1 from startup_radar.weekly_briefing_items i where i.briefing_id=p_id and i.program_id=c.program_id)) then
  raise exception 'Correction may only retain items already published in this briefing'; end if;
 update _correction c set review_note=nullif(btrim(i.snapshot->>'review_note'),'')
  from startup_radar.weekly_briefing_items i where i.briefing_id=p_id and i.program_id=c.program_id
   and c.relevance_status='REVIEW_REQUIRED' and c.review_note is null;
 if exists(select 1 from _correction c where c.relevance_status='REVIEW_REQUIRED'
  and (c.review_note is null or length(c.review_note) not between 1 and 1000)) then
  raise exception 'A REVIEW_REQUIRED item requires its published review note'; end if;
 if exists(select 1 from _correction r join _correction c on true
  where r.relevance_status='REVIEW_REQUIRED' and c.relevance_status<>'REVIEW_REQUIRED'
   and r.display_order<c.display_order) then
  raise exception 'Review-required opportunities must follow confirmed opportunities'; end if;

 insert into startup_radar.admin_audit(action,entity_id,detail)
 values('WEEKLY_PUBLICATION_CORRECTION',p_id::text,jsonb_build_object(
  'reason',trim(p_reason),'previous_briefing',to_jsonb(original),'previous_items',prior,
  'retained',(select coalesce(jsonb_agg(to_jsonb(c) order by c.display_order),'[]') from _correction c),
  'actor','PRIVILEGED_PUBLICATION_OPERATOR','telegram_sent',false));
 delete from startup_radar.weekly_briefing_items i
  where i.briefing_id=p_id and not exists(select 1 from _correction c where c.program_id=i.program_id);
 update startup_radar.weekly_briefing_items set display_order=display_order+100000 where briefing_id=p_id;
 update startup_radar.weekly_briefing_items i set display_order=c.display_order,
  relevance_status=c.relevance_status,restriction_summary=c.restriction_summary,relevance_version=c.relevance_version,
  snapshot=case when c.relevance_status='REVIEW_REQUIRED'
    then jsonb_set(i.snapshot,'{review_note}',to_jsonb(c.review_note),true)
    else i.snapshot-'review_note' end
  from _correction c where i.briefing_id=p_id and i.program_id=c.program_id;
 select count(*),count(*) filter(where change_type='NEW'),count(*) filter(where change_type='UPDATE')
  into kept,fresh,changed from startup_radar.weekly_briefing_items where briefing_id=p_id;
 removed:=removed-kept;
 update startup_radar.weekly_briefings set item_count=kept,new_count=fresh,updated_count=changed,
  summary=p_summary,revision=revision+1,updated_at=now() where id=p_id;
 answer:=jsonb_build_object('briefing_id',p_id,'publication_kind',original.publication_kind,
  'retained',kept,'withdrawn',removed,'new_count',fresh,'updated_count',changed,
  'revision',original.revision+1,'published_at',original.published_at);
 insert into startup_radar.admin_audit(action,entity_id,detail)
 values('WEEKLY_PUBLICATION_CORRECTION_RESULT',p_id::text,jsonb_build_object('result',answer,'telegram_sent',false));
 return answer;
end $$;
revoke all on function startup_radar.apply_publication_correction(uuid,text,text,jsonb) from public,anon,authenticated;
grant execute on function startup_radar.apply_publication_correction(uuid,text,text,jsonb) to service_role;

comment on table startup_radar.weekly_briefing_items is
 'Published editorial snapshots with confirmed relevance or a final REVIEW_REQUIRED appendix carrying a review_note. Unpublished source facts and classifier evidence remain private; all new notices retain the seven-day deadline requirement.';
notify pgrst,'reload schema';
commit;
