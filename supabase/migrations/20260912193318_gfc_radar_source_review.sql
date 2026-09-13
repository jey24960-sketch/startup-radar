begin;
set local lock_timeout='3s';
set local statement_timeout='30s';

-- Detail-only, version-specific projection of source condition explanations.
-- Preserve invoker/RLS and existing team authorization. Do not expose raw metadata,
-- provider diagnostics, source configuration or arbitrary extraction fields.
-- Raw snapshots remain admin-only. This bounded projection intentionally reads
-- that private evidence without granting members the raw table/config/diagnostics.
create function startup_radar.member_source_review(p_version_id uuid)
returns jsonb language plpgsql stable security definer set search_path='' as $$
declare response jsonb;
begin
 if auth.uid() is null or coalesce(public.my_role(),'') not in ('member','admin') then
  raise exception using errcode='42501',message='Verified GFC membership required';
 end if;
    with latest as (
      select distinct on (source_id) source_id,official_detail_url,extraction_metadata
      from startup_radar.program_source_snapshots where program_version_id=p_version_id
      order by source_id,observed_at desc,id desc
    ), findings as (
      select distinct jsonb_build_object(
        'kind',case when flag->>'kind' in (
          'BUSINESS_STATUS_NOT_EXPLICIT','UNCONTROLLED_HISTORY_VALUES',
          'BUSINESS_AGE_BRANCH_NOT_REPRESENTED','BUSINESS_AGE_REFERENCE_DATE_NOT_REPRESENTED',
          'FUTURE_COMMITMENT_NOT_REPRESENTED') then flag->>'kind' else 'UNCLASSIFIED_REVIEW' end,
        'source_url',left(official_detail_url,2048),
        'quotes',coalesce((select jsonb_agg(quote order by quote) from (
          select distinct left(value #>> '{}',500) quote
          from jsonb_array_elements(
            case when jsonb_typeof(flag->'quotes')='array' then flag->'quotes'
                 when jsonb_typeof(flag->'quote')='string' then jsonb_build_array(flag->'quote')
                 else '[]'::jsonb end)
          where jsonb_typeof(value)='string' and btrim(value #>> '{}')<>''
          order by quote limit 3
        ) excerpts),'[]'::jsonb)
      ) item
      from latest cross join lateral jsonb_array_elements(
        case when jsonb_typeof(extraction_metadata->'review_flags')='array'
          then extraction_metadata->'review_flags' else '[]'::jsonb end) flag
      where jsonb_typeof(flag)='object'
      order by item limit 50
    ) select jsonb_agg(item order by item) into response from findings
;
 return coalesce(response,'[]'::jsonb);
end $$;
revoke all on function startup_radar.member_source_review(uuid) from public,anon,authenticated,service_role;
grant execute on function startup_radar.member_source_review(uuid) to authenticated;

create or replace function public.gfc_radar_program_detail(p_program_id uuid,p_team_id uuid default null,p_preset integer default null,p_version_id uuid default null)
returns jsonb language plpgsql stable security invoker set search_path='' as $$
declare scope jsonb; version_id uuid; response jsonb;
begin
 scope=startup_radar.member_scope(p_team_id,p_preset);
 select v.id into version_id from startup_radar.programs p join startup_radar.program_versions v
  on v.program_id=p.id and v.id=coalesce(p_version_id,p.current_version_id) where p.id=p_program_id;
 if version_id is null then raise exception using errcode='P0002',message='Program/version not found'; end if;
 response=startup_radar.member_program_item(version_id,scope);
 return response || jsonb_build_object(
  'source_review',startup_radar.member_source_review(version_id),
  'versions',coalesce((select jsonb_agg(jsonb_build_object('id',id,'version',version,'created_at',created_at) order by version desc)
    from startup_radar.program_versions where program_id=p_program_id),'[]'::jsonb),
  'documents',coalesce((select jsonb_agg(jsonb_build_object('id',id,'original_url',original_url,'filename',filename,'detected_mime',detected_mime,
    'fetch_status',fetch_status,'extraction_status',extraction_status,'error_kind',error_kind,'fetched_at',fetched_at) order by id)
    from startup_radar.documents where program_version_id=version_id),'[]'::jsonb),
  'changes',coalesce((select jsonb_agg(jsonb_build_object('event_type',event_type,'changed_fields',changed_fields,'created_at',created_at) order by created_at desc)
    from startup_radar.program_change_events where program_id=p_program_id),'[]'::jsonb));
end $$;

notify pgrst,'reload schema';
commit;
