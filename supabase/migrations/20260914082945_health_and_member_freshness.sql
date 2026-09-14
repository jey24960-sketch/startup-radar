begin;
set local lock_timeout='3s';
set local statement_timeout='30s';

-- Observation metadata belongs to an exact version, not its mutable parent.
alter table startup_radar.program_versions add column last_observed_at timestamptz;
update startup_radar.program_versions v set last_observed_at=x.observed_at
from (select program_version_id,max(observed_at) observed_at from startup_radar.program_source_snapshots
 where extraction_metadata->>'provider' is distinct from 'source_review' group by program_version_id) x
where x.program_version_id=v.id;
-- Reviewed/revoked stored evidence is not a new fetch. The repository explicitly
-- carries its original source clock forward; old ambiguous review clocks stay unknown.

alter table startup_radar.member_read_state add column last_successful_refresh_at timestamptz,
 add column last_failure_at timestamptz,add column last_failure_reason text;
update startup_radar.member_read_state set last_successful_refresh_at=case when state='SUCCESS' then finished_at end,
 last_failure_at=case when state='FAILED' then finished_at end,last_failure_reason=case when state='FAILED' then error_kind end;

create function startup_radar.freshness(p_at timestamptz) returns text
language sql stable security invoker set search_path='' as $$
 select case when p_at is null or p_at>now()+interval '5 minutes' then 'UNKNOWN'
 when p_at<now()-interval '48 hours' then 'INCIDENT'
 when p_at<now()-interval '24 hours' then 'WARNING' else 'FRESH' end;
$$;

-- Re-evaluate elapsed time on reads. No eligibility fact or historical JSON is rewritten.
create function startup_radar.quality_projection(p_version_id uuid) returns jsonb
language sql stable security invoker set search_path='' as $$
 select jsonb_build_object('state',case when q.state='ACTIONABLE' and startup_radar.freshness(v.last_observed_at)<>'FRESH'
   then 'NEEDS_REVIEW' else coalesce(q.state,'UNVERIFIABLE') end,
  'reasons',to_jsonb(array(select distinct reason from unnest(
   coalesce(q.reasons,array['OTHER_REVIEW_REQUIRED']) || case when startup_radar.freshness(v.last_observed_at)<>'FRESH'
   then array['STALE_SOURCE'] else array[]::text[] end) reason order by reason)),
  'assessed_at',q.assessed_at,'last_source_observation_at',v.last_observed_at,'freshness',startup_radar.freshness(v.last_observed_at))
 from startup_radar.program_versions v left join startup_radar.program_quality q on q.program_version_id=v.id where v.id=p_version_id;
$$;

create function startup_radar.scope_calculation(p_scope jsonb) returns jsonb
language plpgsql stable security invoker set search_path='' as $$
declare config startup_radar.member_read_state; request startup_radar.profile_calculation_requests;
 total_count integer; ready_count integer; last_computed timestamptz; result_state text;
begin
 select * into config from startup_radar.member_read_state where singleton;
 if p_scope->>'key' not like 'preset:%' then
  select * into request from startup_radar.profile_calculation_requests
  where team_id=(p_scope->>'key')::uuid and profile_version=(p_scope->>'version')::integer;
 end if;
 select count(*),count(r.program_version_id) filter(where r.generation=config.generation
  and r.evaluated_on=(now() at time zone 'Asia/Seoul')::date
  and (r.team_id is null or (r.profile_version=(p_scope->>'version')::integer and r.profile_snapshot=p_scope->'profile'))
  and r.response_snapshot=coalesce(a.responses,'{}'::jsonb)),max(r.computed_at)
 into total_count,ready_count,last_computed
 from startup_radar.programs p left join startup_radar.member_program_results r
  on r.program_version_id=p.current_version_id and r.scope_key=p_scope->>'key'
 left join startup_radar.team_program_responses a on a.team_id=r.team_id and a.program_version_id=p.current_version_id
 where p.current_version_id is not null;
 result_state=case when request.state='PENDING' then 'QUEUED'
  when request.state='RUNNING' then 'CALCULATING'
  when ready_count=total_count and (total_count>0 or config.last_successful_refresh_at::date is not null
    and (config.last_successful_refresh_at at time zone 'Asia/Seoul')::date=(now() at time zone 'Asia/Seoul')::date) then 'READY'
  when request.state='FAILED' or config.state='FAILED' then 'FAILED'
  when config.state='RUNNING' then 'CALCULATING'
  when last_computed is not null then 'STALE' else 'NOT_CALCULATED' end;
 return jsonb_build_object('state',result_state,'profile_version',p_scope->'version',
  'requested_at',request.requested_at,'started_at',request.started_at,'finished_at',request.finished_at,
  'last_computed_at',last_computed,'current_results',ready_count,'current_programs',total_count,
  'target_minutes',90,'target_verified',false,
  'delayed',result_state in ('QUEUED','CALCULATING') and coalesce(request.requested_at,config.started_at)<now()-interval '90 minutes');
end $$;
revoke all on function startup_radar.freshness(timestamptz),startup_radar.quality_projection(uuid),startup_radar.scope_calculation(jsonb) from public,anon,authenticated,service_role;
grant execute on function startup_radar.freshness(timestamptz),startup_radar.quality_projection(uuid),startup_radar.scope_calculation(jsonb) to authenticated,service_role;

create or replace function public.gfc_radar_me() returns jsonb
language plpgsql stable security invoker set search_path='' as $$
declare actor uuid=auth.uid(); gfc_role text=public.my_role(); member_teams jsonb;
begin
 if actor is null or coalesce(gfc_role,'') not in ('member','admin') then
  raise exception using errcode='42501',message='Verified GFC membership required'; end if;
 select coalesce(jsonb_agg(jsonb_build_object('id',t.id,'name',t.name,'role',m.role,'profile',p.profile,'version',p.version,
  'calculation',startup_radar.scope_calculation(jsonb_build_object('key',t.id,'version',p.version,'profile',p.profile))) order by t.created_at,t.id),'[]')
 into member_teams from startup_radar.teams t join startup_radar.team_members m on m.team_id=t.id
 join startup_radar.team_profiles p on p.team_id=t.id where m.user_id=actor;
 return jsonb_build_object('user_id',actor,'is_admin',gfc_role='admin','teams',member_teams,'support_types',startup_radar.support_type_contract()->'types');
end $$;

create or replace function public.gfc_radar_update_profile(p_team_id uuid,p_expected_version integer,p_changes jsonb default '{}',p_preset integer default null)
returns jsonb language plpgsql volatile security invoker set search_path='' as $$
declare current_profile startup_radar.team_profiles; edited startup_radar.team_profiles; membership_role text;
begin
 perform public.gfc_radar_me();
 select m.role into membership_role from startup_radar.team_members m where m.team_id=p_team_id and m.user_id=auth.uid();
 if membership_role is null or membership_role not in ('OWNER','EDITOR') then raise exception using errcode='42501',message='Team editing requires owner/editor membership'; end if;
 select * into current_profile from startup_radar.team_profiles where team_id=p_team_id for update;
 if not found then raise exception using errcode='42501',message='Team is not accessible'; end if;
 if p_expected_version is null or current_profile.version<>p_expected_version then raise exception using errcode='40001',message='Profile changed; refresh before editing'; end if;
 update startup_radar.team_profiles set profile=startup_radar.apply_member_profile(current_profile.profile,p_preset,p_changes),version=version+1
 where team_id=p_team_id returning * into edited;
 return to_jsonb(edited)||jsonb_build_object('role',membership_role,'calculation_state','PENDING',
  'calculation',startup_radar.scope_calculation(jsonb_build_object('key',p_team_id,'version',edited.version,'profile',edited.profile)));
end $$;

create or replace function startup_radar.member_program_item(p_version_id uuid,p_scope jsonb)
returns jsonb language plpgsql stable security invoker set search_path='' as $$
declare v startup_radar.program_versions; r startup_radar.member_program_results;
 live_status text; end_at timestamptz; start_at timestamptz; config startup_radar.member_read_state;
 answers jsonb='{}'; answer_revision integer=0;
begin
 select * into v from startup_radar.program_versions where id=p_version_id;
 if not found then raise exception using errcode='P0002',message='Program/version not found'; end if;
 if p_scope->>'key' not like 'preset:%' then
  select x.responses,x.revision into answers,answer_revision from startup_radar.team_program_responses x
  where x.team_id=(p_scope->>'key')::uuid and x.program_version_id=p_version_id;
 end if;
 answers=coalesce(answers,'{}'); answer_revision=coalesce(answer_revision,0);
 select * into config from startup_radar.member_read_state where singleton;
 select * into r from startup_radar.member_program_results x where x.program_version_id=v.id
  and x.scope_key=p_scope->>'key' and x.generation=config.generation
  and x.evaluated_on=(now() at time zone 'Asia/Seoul')::date and x.response_snapshot=answers
  and (x.team_id is null or (x.profile_version=(p_scope->>'version')::integer and x.profile_snapshot=p_scope->'profile'));
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
  'calculation_state',case when r.program_version_id is not null then 'READY' when config.state='FAILED' then 'FAILED' else 'PENDING' end,
  'eligibility',r.eligibility,'recommendation',case when live_status in ('OPEN','UPCOMING') then r.recommendation else null end,
  'evaluation_profile',r.profile_snapshot,'evaluation_responses',r.response_snapshot,'computed_at',r.computed_at);
end $$;

create or replace function public.gfc_radar_programs(
 p_team_id uuid default null,p_preset integer default null,p_q text default '',p_program_type text default null,
 p_status text default null,p_eligibility text default null,p_history boolean default false,
 p_recommended boolean default false,p_limit integer default 30,p_offset integer default 0,
 p_date_from date default null,p_date_to date default null)
returns jsonb language plpgsql stable security invoker set search_path='' as $$
declare scope jsonb; response jsonb;
begin
 scope=startup_radar.member_scope(p_team_id,p_preset);
 if p_limit is null or p_limit not between 1 and 100 or p_offset is null or p_offset<0 or length(coalesce(p_q,''))>200 then
  raise exception using errcode='22023',message='Invalid pagination or query'; end if;
 if p_status is not null and p_status not in ('OPEN','UPCOMING','CLOSED','UNKNOWN') then raise exception using errcode='22023',message='Invalid status'; end if;
 if p_eligibility is not null and p_eligibility not in ('ELIGIBLE','NEEDS_INFO','INELIGIBLE','UNVERIFIABLE') then raise exception using errcode='22023',message='Invalid eligibility'; end if;
 if p_program_type is not null and not exists (
  select 1 from jsonb_array_elements(startup_radar.support_type_contract()->'types') t where t->>'value'=p_program_type
 ) then raise exception using errcode='22023',message='Invalid support type'; end if;
 with candidates as materialized (
  select p.id,p.updated_at,p.application_end_at,startup_radar.member_program_item(p.current_version_id,scope) item
  from startup_radar.programs p where p.current_version_id is not null
   and (coalesce(p_q,'')='' or p.title ilike '%'||p_q||'%' or p.organization ilike '%'||p_q||'%')
   and (p_program_type is null or p_program_type=any(startup_radar.normalize_support_types(p.program_types)))
   and (p_date_from is null or p.application_end_at >= (p_date_from::timestamp at time zone 'Asia/Seoul'))
   and (p_date_to is null or p.application_end_at < ((p_date_to+1)::timestamp at time zone 'Asia/Seoul'))
 ), active as materialized (
  select * from candidates where (coalesce(p_history,false) or item->>'status'<>'CLOSED')
    and (p_status is null or item->>'status'=p_status)
 ), filtered as materialized (
  select * from active where (p_eligibility is null or item->'eligibility'->>'status'=p_eligibility)
   and (not coalesce(p_recommended,false) or (item->'recommendation' <> 'null'::jsonb and item->>'status' in ('OPEN','UPCOMING')))
 ), page as (
  select item,id,updated_at,case when p_recommended then (item->'recommendation'->>'score')::numeric end score
  from filtered order by score desc nulls last,updated_at desc,id limit p_limit offset p_offset
 ) select jsonb_build_object('items',coalesce((select jsonb_agg(item order by score desc nulls last,updated_at desc,id) from page),'[]'::jsonb),
   'total',(select count(*) from filtered),'pending_count',(select count(*) from active where item->>'calculation_state'='PENDING'),
   'failed_count',(select count(*) from active where item->>'calculation_state'='FAILED'),'offset',p_offset,'limit',p_limit)
 into response;
 return response || jsonb_build_object('calculation',startup_radar.scope_calculation(scope));
end $$;

create function startup_radar.health_snapshot() returns jsonb
language plpgsql stable security invoker set search_path='' as $$
declare source_rows jsonb; run_rows jsonb; queue jsonb; computation jsonb; scheduling jsonb;
 documents jsonb; quality jsonb; claims jsonb; workers jsonb; jobs jsonb; notifications jsonb;
 active_count integer; success_count integer;
begin
 select coalesce(jsonb_agg(jsonb_build_object('id',s.id,'slug',s.slug,'name',s.name,'adapter',s.adapter,'enabled',s.enabled,
  'last_attempted_at',s.last_attempted_at,'last_successful_at',s.last_successful_at,
  'last_successful_full_scan_at',s.last_successful_full_scan_at,'last_persisted_at',s.last_persisted_at,
  'last_source_observation_at',s.last_source_observation_at,'last_failure_at',s.last_failure_at,
  'last_failure_reason',case when s.last_failure_reason ~ '^[A-Z_0-9]{1,64}$' then s.last_failure_reason else null end,
  'freshness',startup_radar.freshness(s.last_successful_full_scan_at),'observation_freshness',startup_radar.freshness(s.last_source_observation_at),
  'status',r.status,'discovered_count',r.discovered_count,'fetched_count',r.fetched_count,'parsed_count',r.parsed_count,'latency_ms',r.latency_ms,
  'coverage',coalesce((select jsonb_object_agg(k,v) from jsonb_each(r.coverage) e(k,v)
   where k in ('pages_requested','advertised_records','records_returned','fetched_unique_records','unique_source_ids','persisted_records','rejected_records','failed_records','duplicates','page_cap','pagination_complete')
   and jsonb_typeof(v) in ('number','boolean','null')),'{}') || jsonb_build_object(
   'scope',case when r.coverage->>'scope' in ('OPEN','API_DEFAULT') then r.coverage->>'scope' end,
   'advertised_scope','PRIMARY_QUERY'),
  'failures',coalesce((select jsonb_agg(jsonb_build_object('kind',case when f->>'kind' ~ '^[A-Z_0-9]{1,64}$' then f->>'kind' else 'SOURCE_ERROR' end))
   from jsonb_array_elements(case when jsonb_typeof(r.failures)='array' then r.failures else '[]' end) f),'[]')) order by s.slug),'[]'),
  count(*) filter(where s.enabled),count(*) filter(where s.enabled and r.status='SUCCESS'
   and startup_radar.freshness(s.last_successful_full_scan_at)='FRESH')
 into source_rows,active_count,success_count from startup_radar.sources s left join lateral (
  select r.* from startup_radar.source_run_results r where r.source_id=s.id order by r.created_at desc,r.id desc limit 1
 ) r on true;
 select coalesce(jsonb_agg(jsonb_build_object('id',r.id,'status',r.status,'started_at',r.started_at,'finished_at',r.finished_at,
  'summary',jsonb_build_object('new_programs',case when jsonb_typeof(r.summary->'new_programs')='number' then r.summary->'new_programs' end,
  'eligibility_failed',r.summary->>'eligibility_error' is not null)) order by r.started_at desc),'[]') into run_rows
 from (select * from startup_radar.ingestion_runs order by started_at desc,id desc limit 20) r;
 select jsonb_build_object('pending',count(*) filter(where r.state='PENDING'),'running',count(*) filter(where r.state='RUNNING'),
  'failed',count(*) filter(where r.state='FAILED'),'oldest_pending_at',min(r.requested_at) filter(where r.state='PENDING'),
  'delayed',count(*) filter(where r.state in ('PENDING','RUNNING') and r.requested_at<now()-interval '90 minutes'),
  'target_minutes',90,'target_verified',false) into queue
 from startup_radar.profile_calculation_requests r join startup_radar.team_profiles p on p.team_id=r.team_id and p.version=r.profile_version;
 select jsonb_build_object('state',state,'started_at',started_at,'finished_at',finished_at,'has_error',error_kind is not null,
  'last_successful_refresh_at',last_successful_refresh_at,'last_failure_at',last_failure_at,
  'last_failure_reason',case when last_failure_reason ~ '^[A-Za-z_0-9]{1,64}$' then last_failure_reason end,
  'freshness',startup_radar.freshness(last_successful_refresh_at)) into computation from startup_radar.member_read_state where singleton;
 select jsonb_build_object('enabled',value->'enabled'='true'::jsonb,'ingestion_enabled',value->'ingestion_enabled'='true'::jsonb) into scheduling
 from startup_radar.runtime_settings where key='scheduling';
 select jsonb_build_object('current_total',count(*),'download_success',count(*) filter(where d.fetch_status='SUCCESS'),
  'text_extraction_success',count(*) filter(where d.extraction_status='SUCCESS'),
  'current_failures',count(*) filter(where d.extraction_status in ('FAILED','UNSUPPORTED') or d.fetch_status in ('FAILED','BLOCKED')),
  'pending',count(*) filter(where d.extraction_status='PENDING'),
  'ocr_required',count(*) filter(where d.error_kind in ('DOCUMENT_OCR_REQUIRED','DOCUMENT_OCR_REVIEW','DOCUMENT_OCR_SETUP')),
  'parse_failed',count(*) filter(where d.error_kind in ('DOCUMENT_PARSE','DOCUMENT_PROCESS','DOCUMENT_TIMEOUT','DOCUMENT_EMPTY')),
  'too_large',count(*) filter(where d.error_kind in ('DOCUMENT_LIMIT','SIZE_LIMIT','RESPONSE_TOO_LARGE')),
  'unsupported',count(*) filter(where d.extraction_status='UNSUPPORTED'),
  'historical_total',(select count(*) from startup_radar.documents h where not exists(select 1 from startup_radar.programs p where p.current_version_id=h.program_version_id)),
  'historical_failures',(select count(*) from startup_radar.documents h where (h.extraction_status in ('FAILED','UNSUPPORTED') or h.fetch_status in ('FAILED','BLOCKED'))
   and not exists(select 1 from startup_radar.programs p where p.current_version_id=h.program_version_id))) into documents
 from startup_radar.documents d join startup_radar.programs p on p.current_version_id=d.program_version_id;
 with current_quality as materialized (
  select p.id,p.title,v.id version_id,v.evidence_complete,startup_radar.quality_projection(v.id) q,coalesce(pq.metrics,'{}') metrics,
   case when p.application_end_at<now() then 'CLOSED' when (v.normalized->>'application_start_at')::timestamptz>now() then 'UPCOMING'
    when v.normalized->>'deadline_type' in ('ROLLING','UNTIL_BUDGET_EXHAUSTED') or p.application_end_at is not null then 'OPEN' else 'UNKNOWN' end status,
   (p.application_end_at at time zone 'Asia/Seoul')::date-(now() at time zone 'Asia/Seoul')::date days_left,
   coalesce((select max((m.recommendation->>'score')::numeric) from startup_radar.member_program_results m
    where m.program_version_id=v.id and m.evaluated_on=(now() at time zone 'Asia/Seoul')::date),0) relevance
  from startup_radar.programs p join startup_radar.program_versions v on v.id=p.current_version_id
  left join startup_radar.program_quality pq on pq.program_version_id=v.id
 ), reason_counts as (
  select reason,count(*) count from current_quality c cross join lateral jsonb_array_elements_text(c.q->'reasons') reason group by reason
 ), review_page as (
  select * from current_quality where q->>'state'<>'ACTIONABLE'
  order by (status in ('OPEN','UPCOMING')) desc,case when days_left>=0 then days_left end nulls last,relevance desc,(q->'reasons')::text,id limit 100
 ) select jsonb_build_object('total',count(*),'actionable',count(*) filter(where q->>'state'='ACTIONABLE'),
  'needs_review',count(*) filter(where q->>'state'='NEEDS_REVIEW'),'unverifiable',count(*) filter(where q->>'state'='UNVERIFIABLE'),
  'active_total',count(*) filter(where status in ('OPEN','UPCOMING')),
  'active_actionable',count(*) filter(where status in ('OPEN','UPCOMING') and q->>'state'='ACTIONABLE'),
  'active_needs_review',count(*) filter(where status in ('OPEN','UPCOMING') and q->>'state'='NEEDS_REVIEW'),
  'active_unverifiable',count(*) filter(where status in ('OPEN','UPCOMING') and q->>'state'='UNVERIFIABLE'),
  'active_evidence_complete',count(*) filter(where status in ('OPEN','UPCOMING') and evidence_complete),
  'evidence_complete',count(*) filter(where evidence_complete),
  'd7_backlog',count(*) filter(where status in ('OPEN','UPCOMING') and days_left between 0 and 7 and q->>'state'<>'ACTIONABLE'),
  'd3_backlog',count(*) filter(where status in ('OPEN','UPCOMING') and days_left between 0 and 3 and q->>'state'<>'ACTIONABLE'),
  'ocr_success',coalesce(sum((metrics->>'ocr_success')::integer),0),'reviewed',coalesce(sum((metrics->>'reviewed')::integer),0),
  'reason_pareto',coalesce((select jsonb_agg(to_jsonb(r) order by count desc,reason) from reason_counts r),'[]'),
  'source_evidence',coalesce((select jsonb_agg(x) from (
   select s.slug,count(distinct c.id) total,count(distinct c.id) filter(where c.evidence_complete) evidence_complete,
    count(distinct c.id) filter(where c.status in ('OPEN','UPCOMING')) active_total,
    count(distinct c.id) filter(where c.status in ('OPEN','UPCOMING') and c.evidence_complete) active_evidence_complete
   from current_quality c join startup_radar.program_sources ps on ps.program_id=c.id
   join startup_radar.sources s on s.id=ps.source_id group by s.slug order by s.slug) x),'[]'),
  'review_queue',coalesce((select jsonb_agg(jsonb_build_object('id',id,'version_id',version_id,'title',title,'state',q->'state',
   'status',status,'days_left',days_left,'relevance',relevance,'reasons',q->'reasons')
   order by (status in ('OPEN','UPCOMING')) desc,case when days_left>=0 then days_left end nulls last,relevance desc,(q->'reasons')::text,id) from review_page),'[]'))
 into quality from current_quality;
 with latest as materialized (select distinct on(task_key) * from startup_radar.schedule_task_attempts order by task_key,attempt_number desc)
 select jsonb_build_object('unresolved',count(*) filter(where state not in ('SUCCESS','RUNNING')),
  'running',count(*) filter(where state='RUNNING'),'retry_attempts',(select count(*) from startup_radar.schedule_task_attempts where attempt_number>1),
  'items',coalesce((select jsonb_agg(jsonb_build_object('id',id,'task_key',task_key,'kind',kind,'state',state,
   'attempt_number',attempt_number,'execution_id',execution_id,'next_retry_at',next_retry_at,'reason_code',
   case when reason_code ~ '^[A-Z_0-9]{1,64}$' then reason_code end,
   'recovery',case when state='RUNNING' then 'VERIFY_OWNER_STOPPED' when state='UNCERTAIN' then 'VERIFY_OWNER_AND_SIDE_EFFECTS'
    when state='FAILED_RETRYABLE' and next_retry_at is not null then 'BOUNDED_AUTO_RETRY'
    when state='PENDING' then 'AWAIT_SCHEDULER' else 'FIX_CAUSE_THEN_AUDITED_RETRY' end) order by created_at desc)
   from (select * from latest where state<>'SUCCESS' order by created_at desc limit 100) l),'[]')) into claims from latest;
 select jsonb_build_object('running',count(*) filter(where state='RUNNING'),
  'items',coalesce(jsonb_agg(jsonb_build_object('id',id,'kind',kind,'state',state,'job_id',job_id,'started_at',started_at)
   order by started_at) filter(where state='RUNNING'),'[]')) into workers from startup_radar.worker_executions;
 select jsonb_build_object('queued',count(*) filter(where state='REQUESTED'),'running',count(*) filter(where state='RUNNING')) into jobs from startup_radar.job_requests;
 select jsonb_build_object('enabled_channels',count(*) filter(where s.enabled),
  'deliverable_channels',count(*) filter(where startup_radar.channel_deliverable(s.enabled,s.channel_health,coalesce(p.enabled,true))),
  'blocked_channels',count(*) filter(where s.channel_health='BLOCKED'),
  'pending_batches',(select count(*) from startup_radar.notification_batches where state='PENDING'),
  'uncertain_batches',(select count(*) from startup_radar.notification_batches where state='UNCERTAIN'),
  'last_confirmed_receipt_at',(select max(delivered_at) from startup_radar.notification_batches where state='DELIVERED'),
  'receipt_origin_verified',false) into notifications from startup_radar.telegram_subscriptions s
 left join startup_radar.team_notification_preferences p on p.team_id=s.team_id;
 return jsonb_build_object('as_of',now(),'sources',source_rows,'runs',run_rows,'tracked_sources',jsonb_array_length(source_rows),
  'enabled_sources',active_count,'successful_sources',success_count,
  'tracked_source_success_rate',case when active_count>0 then round(100.0*success_count/active_count,1) end,
  'failure_counts',jsonb_build_object('documents',documents->'current_failures',
   'eligibility',(select count(*) from startup_radar.ingestion_runs where summary->>'eligibility_error' is not null)),
  'documents',documents,'quality',quality,'calculation_queue',queue,'calculation',computation,'scheduling',scheduling,
  'settings',jsonb_build_array(jsonb_build_object('key','scheduling','value',scheduling)),
  'schedule_attempts',claims,'workers',workers,'job_queue',jobs,
  'jobs',coalesce((select jsonb_agg(jsonb_build_object('id',j.id,'kind',j.kind,'state',j.state,'created_at',j.created_at,'finished_at',j.finished_at)
   order by j.created_at desc) from (select * from startup_radar.job_requests order by created_at desc,id desc limit 20) j),'[]'),
  'notifications',notifications,
  'coverage_note','Configured active sources only; healthy means the latest scan succeeded and a full scan completed within 24 hours. Not nationwide coverage.');
end $$;
revoke all on function startup_radar.health_snapshot() from public,anon,authenticated,service_role;
grant execute on function startup_radar.health_snapshot() to service_role;
create or replace function startup_radar.admin_health() returns jsonb
language plpgsql stable security definer set search_path='' as $$
begin
 if auth.uid() is null or coalesce(public.my_role(),'')<>'admin' then raise exception using errcode='42501',message='GFC admin required'; end if;
 return startup_radar.health_snapshot();
end $$;

notify pgrst,'reload schema';
commit;
