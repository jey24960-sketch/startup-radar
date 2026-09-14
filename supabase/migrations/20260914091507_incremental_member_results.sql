begin;
set local lock_timeout='3s';
set local statement_timeout='30s';

-- Stored historical decisions keep their original profile/day/policy context.
-- Current reads retain every strict freshness condition. No read executes AI.
create or replace function startup_radar.member_program_item(p_version_id uuid,p_scope jsonb)
returns jsonb language plpgsql stable security invoker set search_path='' as $$
declare v startup_radar.program_versions; r startup_radar.member_program_results;
 live_status text; end_at timestamptz; start_at timestamptz; config startup_radar.member_read_state;
 answers jsonb='{}'; answer_revision integer=0; is_current boolean;
begin
 select * into v from startup_radar.program_versions where id=p_version_id;
 if not found then raise exception using errcode='P0002',message='Program/version not found'; end if;
 select p.current_version_id=v.id into is_current from startup_radar.programs p where p.id=v.program_id;
 if p_scope->>'key' not like 'preset:%' then
  select x.responses,x.revision into answers,answer_revision from startup_radar.team_program_responses x
  where x.team_id=(p_scope->>'key')::uuid and x.program_version_id=p_version_id;
 end if;
 answers=coalesce(answers,'{}'); answer_revision=coalesce(answer_revision,0);
 select * into config from startup_radar.member_read_state where singleton;
 select * into r from startup_radar.member_program_results x where x.program_version_id=v.id
  and x.scope_key=p_scope->>'key' and (not is_current or (x.generation=config.generation
  and x.evaluated_on=(now() at time zone 'Asia/Seoul')::date and x.response_snapshot=answers
  and (x.team_id is null or (x.profile_version=(p_scope->>'version')::integer and x.profile_snapshot=p_scope->'profile'))));
 end_at=(v.normalized->>'application_end_at')::timestamptz;
 start_at=(v.normalized->>'application_start_at')::timestamptz;
 live_status=case when end_at<now() then 'CLOSED' when start_at>now() then 'UPCOMING'
  when v.normalized->>'deadline_type' in ('ROLLING','UNTIL_BUDGET_EXHAUSTED') or end_at is not null then 'OPEN' else 'UNKNOWN' end;
 return jsonb_build_object('id',v.program_id,'version_id',v.id,'version',v.version,
  'facts',v.normalized || jsonb_build_object('program_types',to_jsonb(startup_radar.normalize_support_types(array(select jsonb_array_elements_text(v.normalized->'program_types'))))),
  'updated_at',v.created_at,'version_created_at',v.created_at,'source_observed_at',v.last_observed_at,
  'source_freshness',startup_radar.freshness(v.last_observed_at),'quality',startup_radar.quality_projection(v.id),'status',live_status,
  'program_responses',jsonb_build_object('responses',answers,'revision',answer_revision),
  'days_left',(end_at at time zone 'Asia/Seoul')::date-(now() at time zone 'Asia/Seoul')::date,
  'calculation_state',case when r.program_version_id is not null then 'READY' when not is_current then 'NOT_STORED'
   when config.state='FAILED' then 'FAILED' else 'PENDING' end,
  'evaluation_context',case when is_current then 'CURRENT' else 'HISTORICAL_STORED' end,
  'evaluation_profile_version',r.profile_version,'evaluated_on',r.evaluated_on,
  'eligibility',r.eligibility,'recommendation',case when live_status in ('OPEN','UPCOMING') then r.recommendation else null end,
  'evaluation_profile',r.profile_snapshot,'evaluation_responses',r.response_snapshot,'computed_at',r.computed_at);
end $$;
notify pgrst,'reload schema';
commit;
