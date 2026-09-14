-- Browser channels now have a bounded worker runtime. Existing admin checks,
-- approved hosts, optimistic revisions and audit remain unchanged.
create or replace function startup_radar.save_opportunity_channel(p_id uuid,p_institution_id uuid,p_revision integer,p_config jsonb,p_enabled boolean,p_note text)
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
 if p_enabled and method='BROWSER' and nullif(coalesce(new_config->>'detail_ready_selector',new_config->>'ready_selector'),'') is null then
  raise exception using errcode='22023',message='A reviewed browser readiness selector must be installed by the server operator';
 end if;
 if not host=any(institution.approved_hosts) or institution.policy_status<>'APPROVED' or method in ('REQUEST','NEWSLETTER') then
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
