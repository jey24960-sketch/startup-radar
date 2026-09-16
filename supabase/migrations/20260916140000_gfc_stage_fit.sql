begin;
set local lock_timeout='3s';
set local statement_timeout='30s';

-- GFC Stage Fit v1.0: "which startup stage benefits most from this opportunity?"
-- Editorial scanning metadata. It is NOT eligibility, NOT a publication gate,
-- and it lives outside weekly.MATERIAL so re-classifying can never turn an
-- unchanged programme into an UPDATE.
create table startup_radar.program_stage_fit (
 program_version_id uuid not null references startup_radar.program_versions on delete cascade,
 stage_version text not null,
 method text not null,
 stage_codes text[] not null default '{}',
 reason text,
 evidence jsonb not null default '{}'::jsonb check(jsonb_typeof(evidence)='object'),
 classified_at timestamptz not null default now(),
 primary key(program_version_id,stage_version),
 check(cardinality(stage_codes)<=2),
 check(stage_codes <@ array['STAGE_0','STAGE_1','STAGE_2','STAGE_3','STAGE_4']::text[])
);
alter table startup_radar.program_stage_fit enable row level security;
revoke all on startup_radar.program_stage_fit from public,anon,authenticated;
grant all on startup_radar.program_stage_fit to service_role;
comment on table startup_radar.program_stage_fit is
 'GFC stage fit per program version (0..2 of STAGE_0..STAGE_4). Editorial metadata outside weekly.MATERIAL; not eligibility. Members receive labels only via gfc_radar_weekly_briefing.';

-- Denormalised onto the published item so the article is a stable snapshot and
-- the website and Telegram read exactly the same stored decision.
alter table startup_radar.weekly_briefing_items
 add column stage_codes text[] not null default '{}',
 add column stage_version text,
 add constraint briefing_item_stage_shape check(
  cardinality(stage_codes)<=2 and stage_codes <@ array['STAGE_0','STAGE_1','STAGE_2','STAGE_3','STAGE_4']::text[]);

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
     'relevance_status',i.relevance_status,'restriction_summary',i.restriction_summary,
     'stage_fit',coalesce((select jsonb_agg(jsonb_build_object('code',c,'label',startup_radar.stage_label(c)) order by o)
                          from unnest(i.stage_codes) with ordinality as s(c,o)),'[]'::jsonb))
    order by i.display_order)
    from startup_radar.weekly_briefing_items i where i.briefing_id=b.id),'[]')) into result
  from startup_radar.weekly_briefings b where b.id=p_id and b.status='PUBLISHED';
 return result;
end $$;
notify pgrst,'reload schema';
commit;
