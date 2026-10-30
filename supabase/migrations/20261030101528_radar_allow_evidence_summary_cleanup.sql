-- Correcting an old page dump changes presentation, not the opportunity or its
-- original preparation window. Keep the current-clock gate for every material
-- revision, new/version-replaced item, and date edit. Never pause notice_policy.
create or replace function startup_radar.enforce_published_item_preparation_time()
returns trigger language plpgsql security invoker set search_path='' as $$
declare enabled boolean; publication startup_radar.weekly_briefings%rowtype;
 legacy_marker constant text:='(^|\n)[[:blank:]]*공식 공고 상세[[:blank:]]*(\n|$)';
begin
 select coalesce((value->>'enabled')::boolean,false) into enabled
 from startup_radar.runtime_settings where key='notice_policy';
 if not coalesce(enabled,false) then return new; end if;
 if tg_op='UPDATE' and new.snapshot is not distinct from old.snapshot
  and new.program_version_id is not distinct from old.program_version_id
  and new.program_id is not distinct from old.program_id
  and new.briefing_id is not distinct from old.briefing_id then return new; end if;
 select * into publication from startup_radar.weekly_briefings where id=new.briefing_id;
 if publication.status='PUBLISHED' then
  if tg_op='UPDATE'
   and new.program_version_id is not distinct from old.program_version_id
   and new.program_id is not distinct from old.program_id
   and new.briefing_id is not distinct from old.briefing_id
   and coalesce(old.snapshot->>'support_summary','') ~ legacy_marker
   and not coalesce(new.snapshot->>'support_summary','') ~ legacy_marker
   and (new.snapshot-array['support_summary','applicant_summary'])
       is not distinct from (old.snapshot-array['support_summary','applicant_summary'])
   and startup_radar.has_notice_preparation_time(new.snapshot,publication.published_at)
   and exists (
    select 1 from startup_radar.admin_audit a
    cross join lateral jsonb_array_elements(
      case when jsonb_typeof(a.detail->'patches')='array' then a.detail->'patches' else '[]'::jsonb end
    ) as p(patch)
    where a.action='WEEKLY_SOURCE_TEXT_REPAIR_AUTHORIZATION'
      and a.entity_id=new.briefing_id::text
      and a.detail->>'actor'='PRIVILEGED_PUBLICATION_OPERATOR'
      and a.detail->>'transaction_id'=txid_current()::text
      and length(btrim(coalesce(a.detail->>'reason','')))>=5
      and p.patch->>'program_id'=new.program_id::text
      and p.patch->>'program_version_id'=new.program_version_id::text
      and p.patch->'before_snapshot'=old.snapshot
      and p.patch->'after_snapshot'=new.snapshot
   ) then
   return new;
  end if;
  if not startup_radar.has_notice_preparation_time(new.snapshot,greatest(publication.published_at,now())) then
   raise exception 'A newly inserted or revised notice item requires seven days of preparation';
  end if;
 end if;
 return new;
end $$;
revoke all on function startup_radar.enforce_published_item_preparation_time() from public,anon,authenticated;

-- Identity/version-only edits must also run the unchanged current-clock gate.
drop trigger published_item_preparation_time_guard on startup_radar.weekly_briefing_items;
create trigger published_item_preparation_time_guard
 before insert or update of snapshot,program_version_id,program_id,briefing_id
 on startup_radar.weekly_briefing_items for each row
 execute function startup_radar.enforce_published_item_preparation_time();

comment on function startup_radar.enforce_published_item_preparation_time() is
 'Current-clock seven-day guard; permits identity-preserving legacy page-dump description cleanup only with exact private audit before/after authorization in the same transaction and seven days at first publication.';
