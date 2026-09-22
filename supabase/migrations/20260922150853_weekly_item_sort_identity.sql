-- Additive read metadata for stable client-side ordering of the COMPLETE item list.
-- No stored snapshot, stage, delivery, title, date, permission or feed-order change.
begin;
set local lock_timeout='5s';
set local statement_timeout='30s';
do $$ begin
 if to_regprocedure('public.gfc_radar_weekly_briefing(uuid)') is null
    or to_regprocedure('startup_radar.require_published_read()') is null then
  raise exception 'existing weekly visibility contract required';
 end if;
end $$;
create or replace function public.gfc_radar_weekly_briefing(p_id uuid)
returns jsonb language plpgsql stable security definer set search_path='' as $$
declare result jsonb;
begin
 perform startup_radar.require_published_read();
 select jsonb_build_object('id',b.id,'week_start',b.week_start,'week_end',b.week_end,'title',b.title,
  'published_at',b.published_at,'item_count',b.item_count,'new_count',b.new_count,'updated_count',b.updated_count,
  'publication_kind',b.publication_kind,'display_start',b.display_start,'display_end',b.display_end,'snapshot_date',b.snapshot_date,
  'summary',b.summary,'revision',b.revision,'items',coalesce((select jsonb_agg(
    jsonb_build_object('program_id',i.program_id,'display_order',i.display_order,'change_type',i.change_type,'facts',i.snapshot,
     'relevance_status',i.relevance_status,'restriction_summary',i.restriction_summary,
     'stage_fit',coalesce((select jsonb_agg(jsonb_build_object('code',c,'label',startup_radar.stage_label(c)) order by o)
                          from unnest(i.stage_codes) with ordinality as s(c,o)),'[]'::jsonb))
    order by i.display_order,i.program_id)
    from startup_radar.weekly_briefing_items i where i.briefing_id=b.id),'[]')) into result
  from startup_radar.weekly_briefings b where b.id=p_id and b.status='PUBLISHED' and b.withdrawn_at is null;
 return result;
end $$;
notify pgrst,'reload schema';
commit;
