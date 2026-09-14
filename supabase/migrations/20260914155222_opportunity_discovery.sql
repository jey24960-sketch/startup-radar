begin;
set local lock_timeout='3s';
set local statement_timeout='30s';
create table startup_radar.institutions (
 id uuid primary key default gen_random_uuid(),slug text unique not null,name text not null,
 kind text not null check(kind in ('GOVERNMENT','PUBLIC_INSTITUTION','VC','AC','CVC','FOUNDATION','UNIVERSITY','CORPORATE','OTHER','UNKNOWN')),
 homepage text not null,approved_hosts text[] not null default '{}',
 policy_status text not null default 'REVIEW_REQUIRED' check(policy_status in ('APPROVED','REVIEW_REQUIRED','RESTRICTED')),
 policy_note text not null default '',checked_at timestamptz,created_at timestamptz not null default now()
);
create table startup_radar.source_channels (
 source_id uuid primary key references startup_radar.sources,
 institution_id uuid not null references startup_radar.institutions,
 connection_state text not null default 'CONFIGURATION_REQUIRED' check(connection_state in ('CONNECTED','CONFIGURATION_REQUIRED','ACCESS_RESTRICTED','TEMPORARY_ERROR','PARTIAL')),
 revision integer not null default 1, last_checked_at timestamptz, last_reason text,
 proof jsonb not null default '{}'
);
create index source_channels_institution_idx on startup_radar.source_channels(institution_id);
create table startup_radar.opportunity_records (
 program_id uuid primary key references startup_radar.programs,
 base_version_id uuid not null references startup_radar.program_versions,
 facts jsonb not null,editorial jsonb not null default '{}',
 confirmed boolean not null default false,included boolean not null default true,
 review_reasons text[] not null default '{}',editorial_conflict boolean not null default false,
 duplicate_of uuid references startup_radar.programs,duplicate_key text,
 revision integer not null default 1,first_seen_at timestamptz not null default now(),
 last_verified_at timestamptz not null default now(),last_changed_at timestamptz not null default now()
);
create index opportunity_duplicate_key_idx on startup_radar.opportunity_records(duplicate_key) where duplicate_key is not null;
create index opportunity_base_version_idx on startup_radar.opportunity_records(base_version_id);
create index opportunity_duplicate_of_idx on startup_radar.opportunity_records(duplicate_of) where duplicate_of is not null;
create index opportunity_active_idx on startup_radar.opportunity_records(last_verified_at desc) where confirmed and included;
create table startup_radar.opportunity_submissions (
 id uuid primary key default gen_random_uuid(),submitted_by uuid references auth.users on delete set null,
 origin text not null check(origin in ('MEMBER','OPERATOR','SEARCH','NEWSLETTER')),
 official_url text not null,description text not null default '',
 state text not null default 'REVIEW' check(state in ('REVIEW','APPLIED','DUPLICATE','EXCLUDED','CONNECTION_REQUIRED')),
 program_id uuid references startup_radar.programs,operator_note text,
 revision integer not null default 1,created_at timestamptz not null default now(),updated_at timestamptz not null default now()
);
create index opportunity_submissions_user_idx on startup_radar.opportunity_submissions(submitted_by,created_at desc);
create index opportunity_submissions_program_idx on startup_radar.opportunity_submissions(program_id) where program_id is not null;
create table startup_radar.discovery_schedule (
 singleton boolean primary key default true check(singleton),enabled boolean not null default false,
 revision integer not null default 1, daily_hour integer not null default 6 check(daily_hour between 0 and 23),
 urgent_delivery_enabled boolean not null default false check(not urgent_delivery_enabled),
 newsletter_connected boolean not null default false,search_connected boolean not null default false
);
insert into startup_radar.discovery_schedule(singleton) values(true);
create table startup_radar.discovery_attempts (
 day date primary key,execution_id uuid not null references startup_radar.worker_executions,
 attempted_at timestamptz not null default now()
);
create index discovery_attempts_execution_idx on startup_radar.discovery_attempts(execution_id);
-- Urgent delivery is intentionally not implemented/enabled: candidates only.
-- Newsletter/search state is set by a verified server-side connector, never a member.

alter table startup_radar.institutions enable row level security;
alter table startup_radar.source_channels enable row level security;
alter table startup_radar.opportunity_records enable row level security;
alter table startup_radar.opportunity_submissions enable row level security;
alter table startup_radar.discovery_schedule enable row level security;
alter table startup_radar.discovery_attempts enable row level security;
revoke all on startup_radar.institutions,startup_radar.source_channels,startup_radar.opportunity_records,
 startup_radar.opportunity_submissions,startup_radar.discovery_schedule,startup_radar.discovery_attempts from public,anon,authenticated;
grant all on startup_radar.institutions,startup_radar.source_channels,startup_radar.opportunity_records,
 startup_radar.opportunity_submissions,startup_radar.discovery_schedule,startup_radar.discovery_attempts to service_role;
grant select on startup_radar.institutions,startup_radar.source_channels,startup_radar.opportunity_records,
 startup_radar.opportunity_submissions,startup_radar.discovery_schedule to authenticated;
create policy institution_member_read on startup_radar.institutions for select to authenticated using((select public.my_role()) in ('member','admin'));
create policy channel_admin_read on startup_radar.source_channels for select to authenticated using((select public.my_role())='admin');
create policy opportunity_member_read on startup_radar.opportunity_records for select to authenticated using(
 (select auth.uid()) is not null and ((select public.my_role())='admin' or
 ((select public.my_role())='member' and confirmed and included and duplicate_of is null)));
create policy submission_own_read on startup_radar.opportunity_submissions for select to authenticated using(
 (select auth.uid()) is not null and ((select public.my_role())='admin' or (submitted_by=(select auth.uid()) and (select public.my_role())='member')));
create policy discovery_admin_read on startup_radar.discovery_schedule for select to authenticated using((select public.my_role())='admin');

create function startup_radar.opportunity_status(f jsonb) returns text language plpgsql stable security invoker set search_path='' as $$
begin
 if coalesce((f->>'cancelled')::boolean,false) then return 'CANCELLED'; end if;
 if f->>'application_end_at' is not null and (f->>'application_end_at')::timestamptz<now() then return 'CLOSED'; end if;
 if f->>'application_start_at' is not null and (f->>'application_start_at')::timestamptz>now() then return 'UPCOMING'; end if;
 if f->>'deadline_type' in ('ROLLING','UNTIL_BUDGET_EXHAUSTED') then return 'ROLLING'; end if;
 if f->>'application_end_at' is not null then return 'OPEN'; end if;
 return 'UNKNOWN';
end $$;
create function public.gfc_opportunities(p_filters jsonb default '{}',p_limit integer default 20,p_offset integer default 0)
returns jsonb language plpgsql stable security invoker set search_path='' as $$
declare result jsonb;
begin
 if auth.uid() is null or coalesce(public.my_role(),'') not in ('member','admin') then raise exception using errcode='42501',message='GFC membership required'; end if;
 if p_filters is null or jsonb_typeof(p_filters)<>'object' or p_limit is null or p_limit not between 1 and 50 or p_offset is null or p_offset<0 or length(p_filters::text)>2000 then
  raise exception using errcode='22023',message='Invalid filters';end if;
 with visible as (
  select o.program_id id,o.facts||o.editorial facts,o.last_verified_at,o.last_changed_at,o.first_seen_at,o.revision,
   o.review_reasons,o.editorial_conflict,startup_radar.opportunity_status(o.facts||o.editorial) status
  from startup_radar.opportunity_records o where confirmed and included and duplicate_of is null
 ), filtered as (
  select * from visible where (coalesce(p_filters->>'q','')='' or facts->>'title' ilike '%'||(p_filters->>'q')||'%')
   and (coalesce(p_filters->>'category','')='' or facts->>'category'=p_filters->>'category')
   and (coalesce(p_filters->>'status','')='' or status=p_filters->>'status')
   and (coalesce(p_filters->>'stage','')='' or (facts->'stages')::text ilike '%'||(p_filters->>'stage')||'%')
   and (coalesce(p_filters->>'region','')='' or (facts->'regions')::text ilike '%'||(p_filters->>'region')||'%')
   and (coalesce(p_filters->>'deadline','')='' or (facts->>'application_end_at')::timestamptz<((p_filters->>'deadline')::date+1)::timestamp at time zone 'Asia/Seoul')
 ) select jsonb_build_object('total',(select count(*) from filtered),'items',coalesce(jsonb_agg(to_jsonb(x)),'[]')) into result
 from (select * from filtered order by (status='OPEN') desc,(facts->>'application_end_at')::timestamptz nulls last,id limit p_limit offset p_offset) x;
 return result;
end $$;
create function public.gfc_opportunity(p_id uuid) returns jsonb language plpgsql stable security invoker set search_path='' as $$
declare result jsonb;
begin
 if auth.uid() is null or coalesce(public.my_role(),'') not in ('member','admin') then raise exception using errcode='42501',message='GFC membership required';end if;
 select jsonb_build_object('id',program_id,'facts',facts||editorial,'source_facts',facts,'revision',revision,
  'last_verified_at',last_verified_at,'last_changed_at',last_changed_at,'first_seen_at',first_seen_at,
  'confirmed',confirmed,'included',included,'editorial',editorial,'review_reasons',review_reasons,'editorial_conflict',editorial_conflict,'status',startup_radar.opportunity_status(facts||editorial)) into result
 from startup_radar.opportunity_records where program_id=p_id;
 return result;
end $$;

create function startup_radar.submit_opportunity(p_url text,p_description text) returns uuid language plpgsql security definer set search_path='' as $$
declare result uuid;
begin
 if auth.uid() is null or coalesce(public.my_role(),'') not in ('member','admin') then raise exception using errcode='42501',message='GFC membership required';end if;
 if p_url is null or length(p_url)>2000 or p_url !~ '^https://[^/@[:space:]<>"\\]+([/][^[:space:]<>"\\]*)?$' or p_description is null or length(p_description)>1000 then
  raise exception using errcode='22023',message='Official HTTPS URL and short description required';end if;
 perform pg_advisory_xact_lock(hashtext(auth.uid()::text));
 select id into result from startup_radar.opportunity_submissions where submitted_by=auth.uid() and official_url=p_url and state in ('REVIEW','CONNECTION_REQUIRED');
 if result is not null then return result;end if;
 if (select count(*) from startup_radar.opportunity_submissions where submitted_by=auth.uid() and created_at>now()-interval '1 day')>=20 then
  raise exception using errcode='22023',message='Daily submission limit reached';end if;
 insert into startup_radar.opportunity_submissions(submitted_by,origin,official_url,description)
 values(auth.uid(),case when public.my_role()='admin' then 'OPERATOR' else 'MEMBER' end,p_url,p_description) returning id into result;
 return result;
end $$;
create function public.gfc_submit_opportunity(p_url text,p_description text) returns uuid language sql security invoker set search_path='' as $$ select startup_radar.submit_opportunity(p_url,p_description) $$;
create function public.gfc_opportunity_submissions() returns jsonb language plpgsql stable security invoker set search_path='' as $$
begin
 if auth.uid() is null or coalesce(public.my_role(),'') not in ('member','admin') then raise exception using errcode='42501',message='GFC membership required';end if;
 return (select coalesce(jsonb_agg(to_jsonb(x)),'[]') from (select id,official_url,description,state,program_id,operator_note,revision,created_at from startup_radar.opportunity_submissions order by created_at desc limit 100) x);
end $$;

create function startup_radar.opportunity_admin_data() returns jsonb language plpgsql stable security definer set search_path='' as $$
declare next_publication timestamptz; result jsonb;
begin
 if auth.uid() is null or coalesce(public.my_role(),'')<>'admin' then raise exception using errcode='42501',message='GFC administrator required';end if;
 select (date_trunc('week',now() at time zone 'Asia/Seoul')+make_interval(days=>weekday,hours=>hour,mins=>minute)) at time zone 'Asia/Seoul' into next_publication from startup_radar.weekly_schedule;
 if next_publication<=now() then next_publication:=next_publication+interval '7 days';end if;
 result:=jsonb_build_object('institutions',(select coalesce(jsonb_agg(to_jsonb(i) order by name),'[]') from startup_radar.institutions i),
 'channels',(select coalesce(jsonb_agg(jsonb_build_object('id',s.id,'institution_id',c.institution_id,'name',s.name,'enabled',s.enabled,
   'method',coalesce(s.config->>'method',s.adapter),'url',s.config->>'url','state',c.connection_state,'reason',c.last_reason,'revision',c.revision,
   'last_attempted_at',s.last_attempted_at,'last_successful_at',s.last_successful_at,'proof',c.proof,
   'config',jsonb_build_object('link_selector',s.config->>'link_selector','detail_selector',s.config->>'detail_selector','title_selector',s.config->>'title_selector','max_pages',s.config->'max_pages','max_records',s.config->'max_records')) order by s.name),'[]') from startup_radar.source_channels c join startup_radar.sources s on s.id=c.source_id),
 'review',(select coalesce(jsonb_agg(to_jsonb(x)),'[]') from (select program_id id,facts,editorial,confirmed,included,review_reasons,editorial_conflict,duplicate_of,revision,last_verified_at from startup_radar.opportunity_records where cardinality(review_reasons)>0 or editorial_conflict or not confirmed order by last_verified_at desc limit 100) x),
 'urgent_candidates',(select coalesce(jsonb_agg(jsonb_build_object('id',program_id,'title',(facts||editorial)->>'title','deadline',(facts||editorial)->>'application_end_at')),'[]') from startup_radar.opportunity_records
   where confirmed and included and duplicate_of is null and first_seen_at>now()-interval '7 days'
   and ((facts||editorial)->>'application_end_at')::timestamptz between now() and next_publication),
 'schedule',(select to_jsonb(d) from startup_radar.discovery_schedule d),
 'metrics',jsonb_build_object('candidate_institutions',(select count(*) from startup_radar.institutions),
   'connected_institutions',(select count(distinct institution_id) from startup_radar.source_channels where connection_state='CONNECTED'),
   'recently_healthy_institutions',(select count(distinct c.institution_id) from startup_radar.source_channels c join startup_radar.sources s on s.id=c.source_id where c.connection_state='CONNECTED' and s.last_successful_at>now()-interval '36 hours'),
   'opportunities',(select count(*) from startup_radar.opportunity_records),
   'review_pending',(select count(*) from startup_radar.opportunity_records where cardinality(review_reasons)>0 or editorial_conflict or not confirmed),
   'date_confirmed',(select count(*) from startup_radar.opportunity_records where facts->>'application_end_at' is not null),
   'application_link_confirmed',(select count(*) from startup_radar.opportunity_records where facts->>'application_link_verified'='true'),
   'source_failures',(select count(*) from startup_radar.source_channels where connection_state in ('TEMPORARY_ERROR','ACCESS_RESTRICTED')),
   'partial_sources',(select count(*) from startup_radar.source_channels where connection_state='PARTIAL'),
   'new_last_day',(select count(*) from startup_radar.opportunity_records where first_seen_at>now()-interval '1 day'),
   'changed_last_day',(select count(*) from startup_radar.opportunity_records where last_changed_at>now()-interval '1 day' and first_seen_at<last_changed_at),
   'by_category',(select coalesce(jsonb_agg(to_jsonb(x)),'[]') from (select facts->>'category' category,count(*) count from startup_radar.opportunity_records group by 1) x)),
 'discovery_delay_note','Discovery delay is unknown unless an explicit original publication timestamp exists. Candidate count is not nationwide coverage.');
 return result;
end $$;
create function public.gfc_opportunity_admin() returns jsonb language sql stable security invoker set search_path='' as $$ select startup_radar.opportunity_admin_data() $$;

create function startup_radar.review_opportunity(p_id uuid,p_revision integer,p_patch jsonb,p_included boolean,p_note text)
returns jsonb language plpgsql security definer set search_path='' as $$
declare old startup_radar.opportunity_records; k text; v text; merged jsonb;
begin
 if auth.uid() is null or coalesce(public.my_role(),'')<>'admin' then raise exception using errcode='42501',message='GFC administrator required';end if;
 if p_note is null or length(trim(p_note)) not between 5 and 500 or p_patch is null or jsonb_typeof(p_patch)<>'object' or length(p_patch::text)>20000 or p_included is null then
  raise exception using errcode='22023',message='Correction fields and reason required';end if;
 select * into old from startup_radar.opportunity_records where program_id=p_id for update;
 if not found then raise exception using errcode='22023',message='Opportunity not found';end if;
 if p_revision is null or old.revision<>p_revision then raise exception using errcode='40001',message='Opportunity changed; reload';end if;
 for k,v in select key,value from jsonb_each_text(p_patch) loop
  if k not in ('title','organization','category','participation','support_summary','applicant_summary','fee','investment_terms','application_end_at','application_start_at','application_end_precision','application_start_precision','deadline_type')
   or (p_patch->k<>'null'::jsonb and jsonb_typeof(p_patch->k)<>'string') or length(v)>8000 then raise exception using errcode='22023',message='Unsupported editorial field';end if;
  if k in ('title','organization') and (v is null or length(trim(v))=0) then raise exception using errcode='22023',message='Title/organization required';end if;
  if k='category' and (v is null or v not in ('PUBLIC_SUPPORT','COMPETITION','ACCELERATOR','OPEN_INNOVATION','EDUCATION_SPACE','EVENT','INVESTMENT_REVIEW','OTHER')) then raise exception using errcode='22023',message='Unknown category';end if;
  if k='participation' and (v is null or v not in ('TEAM_RECRUITMENT','EVENT_ATTENDANCE','INVESTMENT_APPLICATION','UNKNOWN')) then raise exception using errcode='22023',message='Unknown participation';end if;
  if k like 'application%at' and v is not null then
   if v !~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$' then raise exception using errcode='22023',message='Date timezone required';end if;perform v::timestamptz;end if;
  if k like '%precision' and (v is null or v not in ('UNKNOWN','DATE','DATETIME')) then raise exception using errcode='22023',message='Unknown precision';end if;
  if k='deadline_type' and (v is null or v not in ('UNKNOWN','FIXED_DATE','ROLLING','UNTIL_BUDGET_EXHAUSTED')) then raise exception using errcode='22023',message='Unknown deadline type';end if;
 end loop;
 merged:=old.facts||old.editorial||p_patch;
 if (merged->>'application_start_at')::timestamptz>(merged->>'application_end_at')::timestamptz then raise exception using errcode='22023',message='Start after deadline';end if;
 -- Manual inclusion cannot turn an unverified external submission into a published notice.
 if p_included and not old.confirmed then raise exception using errcode='22023',message='Official recruitment verification required';end if;
 update startup_radar.opportunity_records set editorial=editorial||p_patch,included=p_included,editorial_conflict=false,
  review_reasons=array_remove(review_reasons,'EDITORIAL_CONFLICT'),revision=revision+1 where program_id=p_id;
 insert into startup_radar.admin_audit(actor_id,action,entity_id,detail) values(auth.uid(),'OPPORTUNITY_CORRECTION',p_id::text,
  jsonb_build_object('reason',p_note,'before',to_jsonb(old),'patch',p_patch,'included',p_included));
 return jsonb_build_object('id',p_id,'revision',old.revision+1);
end $$;
create function public.gfc_review_opportunity(p_id uuid,p_revision integer,p_patch jsonb,p_included boolean,p_note text)
returns jsonb language sql security invoker set search_path='' as $$select startup_radar.review_opportunity(p_id,p_revision,p_patch,p_included,p_note)$$;

create function startup_radar.resolve_opportunity_submission(p_id uuid,p_revision integer,p_state text,p_program_id uuid,p_note text)
returns jsonb language plpgsql security definer set search_path='' as $$
declare old startup_radar.opportunity_submissions;
begin
 if auth.uid() is null or coalesce(public.my_role(),'')<>'admin' then raise exception using errcode='42501',message='GFC administrator required';end if;
 if p_state is null or p_state not in ('REVIEW','APPLIED','DUPLICATE','EXCLUDED','CONNECTION_REQUIRED') or p_note is null or length(trim(p_note)) not between 5 and 500 then raise exception using errcode='22023',message='Decision and reason required';end if;
 select * into old from startup_radar.opportunity_submissions where id=p_id for update;
 if not found or p_revision is null or old.revision<>p_revision then raise exception using errcode='40001',message='Submission changed; reload';end if;
 if p_state in ('APPLIED','DUPLICATE') and not exists(select 1 from startup_radar.opportunity_records o where o.program_id=p_program_id and confirmed
  and (facts->>'official_url'=old.official_url or facts->>'application_url'=old.official_url or exists(select 1 from startup_radar.program_sources s where s.program_id=o.program_id and s.official_detail_url=old.official_url))) then
  raise exception using errcode='22023',message='Matching verified official source required';end if;
 update startup_radar.opportunity_submissions set state=p_state,program_id=p_program_id,operator_note=p_note,revision=revision+1,updated_at=now() where id=p_id;
 insert into startup_radar.admin_audit(actor_id,action,entity_id,detail) values(auth.uid(),'OPPORTUNITY_SUBMISSION_REVIEW',p_id::text,jsonb_build_object('before',to_jsonb(old),'state',p_state,'reason',p_note));
 return jsonb_build_object('id',p_id,'revision',old.revision+1);
end $$;
create function public.gfc_resolve_opportunity_submission(p_id uuid,p_revision integer,p_state text,p_program_id uuid,p_note text) returns jsonb language sql security invoker set search_path='' as $$ select startup_radar.resolve_opportunity_submission(p_id,p_revision,p_state,p_program_id,p_note) $$;

create function startup_radar.save_opportunity_channel(p_id uuid,p_institution_id uuid,p_revision integer,p_config jsonb,p_enabled boolean,p_note text)
returns jsonb language plpgsql security definer set search_path='' as $$
declare institution startup_radar.institutions; old startup_radar.source_channels; current_config jsonb; new_config jsonb;
 source uuid; host text; method text; k text; state text; editable text[]:=array['url','method','name','link_selector','detail_selector','title_selector','max_pages','max_records','next_selector','empty_marker'];
begin
 if auth.uid() is null or coalesce(public.my_role(),'')<>'admin' then raise exception using errcode='42501',message='GFC administrator required';end if;
 if p_note is null or length(trim(p_note)) not between 5 and 500 or p_config is null or jsonb_typeof(p_config)<>'object' or length(p_config::text)>6000 or p_enabled is null then raise exception using errcode='22023',message='Channel fields and reason required';end if;
 for k in select jsonb_object_keys(p_config) loop if not k=any(editable) then raise exception using errcode='22023',message='Field requires developer review';end if;end loop;
 select * into institution from startup_radar.institutions where id=p_institution_id;
 if not found then raise exception using errcode='22023',message='Select a registered institution';end if;
 if p_id is not null then
  select * into old from startup_radar.source_channels where source_id=p_id and institution_id=p_institution_id for update;
  if not found or p_revision is null or old.revision<>p_revision then raise exception using errcode='40001',message='Channel changed; reload';end if;
  select config into current_config from startup_radar.sources where id=p_id;
  if not coalesce((current_config->>'opportunity_channel')::boolean,false) then raise exception using errcode='22023',message='Official API credentials and scope are managed by server operators';end if;
 else current_config:='{}';end if;
 new_config:=current_config||p_config;method:=new_config->>'method';
 if method is null or method not in ('BOARD','PAGE','RSS','BROWSER','NEWSLETTER','REQUEST') then raise exception using errcode='22023',message='Unsupported method';end if;
 if new_config->>'url' is null or length(new_config->>'url')>2000 or new_config->>'url' !~ '^https://[^/@[:space:]<>"\\]+([/][^[:space:]<>"\\]*)?$' then raise exception using errcode='22023',message='HTTPS channel URL required';end if;
 host:=substring(new_config->>'url' from '^https://([^/:?#]+)');
 if (new_config->>'max_pages')::integer not between 1 and 5 or (new_config->>'max_records')::integer not between 1 and 100 then raise exception using errcode='22023',message='Channel limits exceeded';end if;
 if length(coalesce(new_config->>'link_selector',''))>300 or length(coalesce(new_config->>'detail_selector',''))>300 or length(coalesce(new_config->>'title_selector',''))>300 then raise exception using errcode='22023',message='Selector too long';end if;
 if method='BOARD' and nullif(new_config->>'link_selector','') is null then raise exception using errcode='22023',message='Board selector required';end if;
 -- A new domain is a request, never an automatically approved allowlist entry.
 if not host=any(institution.approved_hosts) or institution.policy_status<>'APPROVED' or method in ('REQUEST','NEWSLETTER','BROWSER') then
  if p_enabled then raise exception using errcode='22023',message='Connection/policy verification is required before activation';end if;
  state:='CONFIGURATION_REQUIRED';
 else state:='CONFIGURATION_REQUIRED';end if;
 new_config:=new_config||jsonb_build_object('opportunity_channel',true,'organization',institution.name,'organization_type',institution.kind,
  'allowed_hosts',to_jsonb(institution.approved_hosts),'policy_status',case when host=any(institution.approved_hosts) then institution.policy_status else 'REVIEW_REQUIRED' end,
  'max_pages',coalesce((new_config->>'max_pages')::integer,2),'max_records',coalesce((new_config->>'max_records')::integer,30));
 if p_id is null then
  source:=gen_random_uuid();
  insert into startup_radar.sources(id,slug,name,adapter,config,enabled) values(source,'channel-'||source::text,coalesce(nullif(new_config->>'name',''),institution.name),'HTML',new_config,p_enabled);
  insert into startup_radar.source_channels(source_id,institution_id,connection_state,last_reason) values(source,institution.id,state,'NEW_CHANNEL_AWAITS_FIRST_SUCCESS');
 else
  source:=p_id;
  update startup_radar.sources set config=new_config,enabled=p_enabled,name=coalesce(nullif(new_config->>'name',''),name) where id=source;
  update startup_radar.source_channels set connection_state=state,revision=revision+1,last_reason='CONFIGURATION_CHANGED_AWAITS_VALIDATION' where source_id=source;
 end if;
 insert into startup_radar.admin_audit(actor_id,action,entity_id,detail) values(auth.uid(),'OPPORTUNITY_CHANNEL_EDIT',source::text,
  jsonb_build_object('before',current_config,'after',new_config,'enabled',p_enabled,'reason',p_note));
 return jsonb_build_object('id',source,'state',state);
end $$;
create function public.gfc_save_opportunity_channel(p_id uuid,p_institution_id uuid,p_revision integer,p_config jsonb,p_enabled boolean,p_note text) returns jsonb language sql security invoker set search_path='' as $$select startup_radar.save_opportunity_channel(p_id,p_institution_id,p_revision,p_config,p_enabled,p_note)$$;
create function startup_radar.set_discovery_schedule(p_enabled boolean,p_hour integer,p_revision integer,p_note text) returns jsonb language plpgsql security definer set search_path='' as $$
declare old jsonb;
begin
 if auth.uid() is null or coalesce(public.my_role(),'')<>'admin' then raise exception using errcode='42501',message='GFC administrator required';end if;
 if p_enabled is null or p_hour is null or p_hour not between 0 and 23 or p_note is null or length(trim(p_note)) not between 5 and 500 then raise exception using errcode='22023',message='Schedule and reason required';end if;
 select to_jsonb(d) into old from startup_radar.discovery_schedule d where singleton for update;
 if p_revision is null or (old->>'revision')::integer<>p_revision then raise exception using errcode='40001',message='Schedule changed; reload';end if;
 update startup_radar.discovery_schedule set enabled=p_enabled,daily_hour=p_hour,revision=revision+1 where singleton;
 insert into startup_radar.admin_audit(actor_id,action,entity_id,detail) values(auth.uid(),'DISCOVERY_SCHEDULE_EDIT','daily',jsonb_build_object('before',old,'enabled',p_enabled,'hour',p_hour,'reason',p_note));
 return jsonb_build_object('enabled',p_enabled,'daily_hour',p_hour,'revision',(old->>'revision')::integer+1);
end $$;
create function public.gfc_set_discovery_schedule(p_enabled boolean,p_hour integer,p_revision integer,p_note text) returns jsonb language sql security invoker set search_path='' as $$select startup_radar.set_discovery_schedule(p_enabled,p_hour,p_revision,p_note)$$;

create function startup_radar.resolve_opportunity_duplicate(p_id uuid,p_target uuid,p_revision integer,p_note text) returns jsonb language plpgsql security definer set search_path='' as $$
declare old startup_radar.opportunity_records; target startup_radar.opportunity_records;
begin
 if auth.uid() is null or coalesce(public.my_role(),'')<>'admin' then raise exception using errcode='42501',message='GFC administrator required';end if;
 if p_id=p_target or p_note is null or length(trim(p_note)) not between 5 and 500 then raise exception using errcode='22023',message='Distinct target and reason required';end if;
 perform pg_advisory_xact_lock(782394201);
 select * into old from startup_radar.opportunity_records where program_id=p_id for update;
 select * into target from startup_radar.opportunity_records where program_id=p_target for update;
 if old.program_id is null or target.program_id is null or p_revision is null or old.revision<>p_revision then raise exception using errcode='40001',message='Record changed; reload';end if;
 if target.duplicate_of is not null or not target.confirmed or old.facts->'participation' is distinct from target.facts->'participation'
  or old.facts->'cohort' is distinct from target.facts->'cohort' or old.facts->'year' is distinct from target.facts->'year'
  or old.facts->'regions' is distinct from target.facts->'regions' then raise exception using errcode='22023',message='Different cohort, region or participation cannot be merged';end if;
 -- Keep both original records and their histories. Canonical projection links them.
 update startup_radar.opportunity_records set duplicate_of=p_target,included=false,review_reasons=array_remove(review_reasons,'POSSIBLE_DUPLICATE'),revision=revision+1 where program_id=p_id;
 update startup_radar.opportunity_records set facts=jsonb_set(facts,'{sources}',coalesce(facts->'sources','[]')||coalesce(old.facts->'sources','[]')),revision=revision+1 where program_id=p_target;
 insert into startup_radar.admin_audit(actor_id,action,entity_id,detail) values(auth.uid(),'OPPORTUNITY_DUPLICATE_REVIEW',p_id::text,jsonb_build_object('before',to_jsonb(old),'target',p_target,'reason',p_note));
 return jsonb_build_object('id',p_id,'target',p_target);
end $$;
create function public.gfc_resolve_opportunity_duplicate(p_id uuid,p_target uuid,p_revision integer,p_note text) returns jsonb language sql security invoker set search_path='' as $$select startup_radar.resolve_opportunity_duplicate(p_id,p_target,p_revision,p_note)$$;
revoke all on function startup_radar.save_opportunity_channel(uuid,uuid,integer,jsonb,boolean,text),public.gfc_save_opportunity_channel(uuid,uuid,integer,jsonb,boolean,text),
 startup_radar.set_discovery_schedule(boolean,integer,integer,text),public.gfc_set_discovery_schedule(boolean,integer,integer,text),
 startup_radar.resolve_opportunity_duplicate(uuid,uuid,integer,text),public.gfc_resolve_opportunity_duplicate(uuid,uuid,integer,text) from public,anon,authenticated,service_role;
grant execute on function startup_radar.save_opportunity_channel(uuid,uuid,integer,jsonb,boolean,text),public.gfc_save_opportunity_channel(uuid,uuid,integer,jsonb,boolean,text),
 startup_radar.set_discovery_schedule(boolean,integer,integer,text),public.gfc_set_discovery_schedule(boolean,integer,integer,text),
 startup_radar.resolve_opportunity_duplicate(uuid,uuid,integer,text),public.gfc_resolve_opportunity_duplicate(uuid,uuid,integer,text) to authenticated;

-- Explicit grants, including private implementations; every mutation checks auth.uid and my_role.
revoke all on function startup_radar.opportunity_status(jsonb),startup_radar.submit_opportunity(text,text),
 startup_radar.opportunity_admin_data(),startup_radar.review_opportunity(uuid,integer,jsonb,boolean,text),
 startup_radar.resolve_opportunity_submission(uuid,integer,text,uuid,text),
 public.gfc_opportunities(jsonb,integer,integer),public.gfc_opportunity(uuid),public.gfc_submit_opportunity(text,text),
 public.gfc_opportunity_submissions(),public.gfc_opportunity_admin(),public.gfc_review_opportunity(uuid,integer,jsonb,boolean,text),
 public.gfc_resolve_opportunity_submission(uuid,integer,text,uuid,text) from public,anon,authenticated,service_role;
grant execute on function startup_radar.opportunity_status(jsonb),startup_radar.submit_opportunity(text,text),
 startup_radar.opportunity_admin_data(),startup_radar.review_opportunity(uuid,integer,jsonb,boolean,text),
 startup_radar.resolve_opportunity_submission(uuid,integer,text,uuid,text),
 public.gfc_opportunities(jsonb,integer,integer),public.gfc_opportunity(uuid),public.gfc_submit_opportunity(text,text),
 public.gfc_opportunity_submissions(),public.gfc_opportunity_admin(),public.gfc_review_opportunity(uuid,integer,jsonb,boolean,text),
 public.gfc_resolve_opportunity_submission(uuid,integer,text,uuid,text) to authenticated;
grant execute on function startup_radar.opportunity_status(jsonb) to service_role;

create function startup_radar.request_institution(p_name text,p_url text,p_note text) returns uuid language plpgsql security definer set search_path='' as $$
declare new_id uuid:=gen_random_uuid();
begin
 if auth.uid() is null or coalesce(public.my_role(),'')<>'admin' then raise exception using errcode='42501',message='GFC administrator required';end if;
 if p_name is null or length(trim(p_name)) not between 2 and 150 or p_note is null or length(trim(p_note)) not between 5 and 500
  or p_url is null or length(p_url)>2000 or p_url !~ '^https://[^/@[:space:]<>"\\]+([/][^[:space:]<>"\\]*)?$' then raise exception using errcode='22023',message='Official institution name, HTTPS URL and reason required';end if;
 insert into startup_radar.institutions(id,slug,name,kind,homepage,policy_note) values(new_id,'requested-'||new_id::text,p_name,'UNKNOWN',p_url,p_note);
 insert into startup_radar.admin_audit(actor_id,action,entity_id,detail) values(auth.uid(),'INSTITUTION_CONNECTION_REQUEST',new_id::text,jsonb_build_object('url',p_url,'reason',p_note));
 return new_id;
end $$;
create function public.gfc_request_institution(p_name text,p_url text,p_note text) returns uuid language sql security invoker set search_path='' as $$ select startup_radar.request_institution(p_name,p_url,p_note) $$;
revoke all on function startup_radar.request_institution(text,text,text),public.gfc_request_institution(text,text,text) from public,anon,authenticated,service_role;
grant execute on function startup_radar.request_institution(text,text,text),public.gfc_request_institution(text,text,text) to authenticated;

-- Legacy recommendation/detail routes must respect catalogue exclusions too.
create function startup_radar.opportunity_history(p_id uuid) returns jsonb language plpgsql stable security definer set search_path='' as $$
begin
 if auth.uid() is null or coalesce(public.my_role(),'')<>'admin' then raise exception using errcode='42501',message='GFC administrator required';end if;
 return jsonb_build_object('edits',(select coalesce(jsonb_agg(to_jsonb(a)),'[]') from
  (select created_at,action,detail->>'reason' reason,detail->'patch' patch,detail->'before' previous from startup_radar.admin_audit where entity_id=p_id::text and action in ('OPPORTUNITY_CORRECTION','OPPORTUNITY_DUPLICATE_REVIEW') order by created_at desc limit 30) a),
  'versions',(select coalesce(jsonb_agg(to_jsonb(v)),'[]') from (select version,created_at,normalized->>'title' title,normalized->>'application_end_at' deadline from startup_radar.program_versions where program_id=p_id order by version desc limit 30) v));
end $$;
create function public.gfc_opportunity_history(p_id uuid) returns jsonb language sql stable security invoker set search_path='' as $$select startup_radar.opportunity_history(p_id)$$;
revoke all on function startup_radar.opportunity_history(uuid),public.gfc_opportunity_history(uuid) from public,anon,authenticated,service_role;
grant execute on function startup_radar.opportunity_history(uuid),public.gfc_opportunity_history(uuid) to authenticated;
create function startup_radar.opportunity_visible(p_id uuid) returns boolean language sql stable security definer set search_path='' as $$
 select auth.uid() is not null and (public.my_role()='admin' or (public.my_role()='member' and
  not exists(select 1 from startup_radar.opportunity_records where program_id=p_id and (not confirmed or not included or duplicate_of is not null))))
$$;
revoke all on function startup_radar.opportunity_visible(uuid) from public,anon,authenticated,service_role;
grant execute on function startup_radar.opportunity_visible(uuid) to authenticated;
create policy opportunity_program_visibility on startup_radar.programs as restrictive for select to authenticated using((select startup_radar.opportunity_visible(id)));
create policy opportunity_version_visibility on startup_radar.program_versions as restrictive for select to authenticated using((select startup_radar.opportunity_visible(program_id)));
notify pgrst,'reload schema';
commit;
