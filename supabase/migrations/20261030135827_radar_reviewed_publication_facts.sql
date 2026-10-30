-- Reviewed curation is separate from immutable source programs and versions.
create table startup_radar.publication_reviews (
 program_id uuid primary key references startup_radar.programs(id),
 reviewed_version_id uuid not null references startup_radar.program_versions(id),
 disposition text not null check(disposition in ('RETAIN','EXCLUDE','HOLD','DUPLICATE')),
 representative_program_id uuid references startup_radar.programs(id),
 snapshot_patch jsonb not null default '{}'::jsonb,
 relevance_status text check(relevance_status in ('GFC_RELEVANT','CONDITIONAL')),
 restriction_summary text,
 reason text not null check(length(btrim(reason)) between 5 and 2000),
 evidence jsonb not null,
 active boolean not null default true,
 reviewed_at timestamptz not null default now(),
 check(jsonb_typeof(snapshot_patch)='object' and
       snapshot_patch-array['support_summary','applicant_summary','organization']='{}'::jsonb),
 check(disposition<>'RETAIN' or relevance_status is not null),
 check(relevance_status is distinct from 'CONDITIONAL' or nullif(btrim(restriction_summary),'') is not null),
 check((disposition='DUPLICATE')=(representative_program_id is not null)),
 check(representative_program_id is distinct from program_id)
);
create index publication_reviews_version_idx on startup_radar.publication_reviews(reviewed_version_id);
create index publication_reviews_representative_idx on startup_radar.publication_reviews(representative_program_id)
 where representative_program_id is not null;
alter table startup_radar.publication_reviews enable row level security;
revoke all on startup_radar.publication_reviews from public,anon,authenticated;
comment on table startup_radar.publication_reviews is
 'Private operator-reviewed curation. HOLD/EXCLUDE/DUPLICATE require explicit release; descriptive RETAIN patches apply only to the reviewed immutable version. Every change must be recorded in admin_audit.';

create function startup_radar.audit_publication_review_change()
returns trigger language plpgsql security invoker set search_path='' as $$
begin
 if tg_op<>'DELETE' and not exists(select 1 from startup_radar.program_versions
   where id=new.reviewed_version_id and program_id=new.program_id) then
  raise exception 'Reviewed version must belong to the reviewed program';
 end if;
 insert into startup_radar.admin_audit(action,entity_id,detail)
 values('PUBLICATION_REVIEW_'||tg_op,coalesce(new.program_id,old.program_id)::text,
  jsonb_build_object('actor','PRIVILEGED_PUBLICATION_OPERATOR','before',
   case when tg_op='INSERT' then null else to_jsonb(old) end,'after',
   case when tg_op='DELETE' then null else to_jsonb(new) end));
 return coalesce(new,old);
end $$;
revoke all on function startup_radar.audit_publication_review_change() from public,anon,authenticated;
create trigger publication_review_audit before insert or update or delete
 on startup_radar.publication_reviews for each row
 execute function startup_radar.audit_publication_review_change();

-- An exact same-transaction private authorization permits reviewed descriptive
-- repairs at the original preparation window. Identity, dates, version, URLs and
-- all other substantive facts retain the ordinary current-clock guard.
create or replace function startup_radar.enforce_published_item_preparation_time()
returns trigger language plpgsql security invoker set search_path='' as $$
declare enabled boolean; publication startup_radar.weekly_briefings%rowtype;

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
   and (new.snapshot-array['support_summary','applicant_summary','organization','review_note'])
       is not distinct from (old.snapshot-array['support_summary','applicant_summary','organization','review_note'])
   and startup_radar.has_notice_preparation_time(new.snapshot,publication.published_at)
   and exists (
    select 1 from startup_radar.admin_audit a
    cross join lateral jsonb_array_elements(
      case when jsonb_typeof(a.detail->'patches')='array' then a.detail->'patches' else '[]'::jsonb end
    ) as p(patch)
    where a.action in ('WEEKLY_SOURCE_TEXT_REPAIR_AUTHORIZATION','WEEKLY_EDITORIAL_REPAIR_AUTHORIZATION')
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
 'Current-clock seven-day guard; permits identity-preserving reviewed descriptive corrections only with exact private audit before/after authorization in the same transaction and seven days at first publication.';
