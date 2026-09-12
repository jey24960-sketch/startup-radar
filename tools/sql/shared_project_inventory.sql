with ns as (select oid,nspname from pg_namespace where nspname in ('public','auction_private','auth','storage')),
objects as (
select 'schema' kind,n.nspname schema_name,n.nspname name,to_jsonb(n0)-'oid' definition from pg_namespace n0 join ns n on n.oid=n0.oid
union all
select 'relation',n.nspname,c.relname,jsonb_build_object('kind',c.relkind,'owner',pg_get_userbyid(c.relowner),'rls',c.relrowsecurity,'force_rls',c.relforcerowsecurity,'acl',c.relacl,'options',c.reloptions,'view',case when c.relkind in ('v','m') then pg_get_viewdef(c.oid,true) end) from pg_class c join ns n on n.oid=c.relnamespace where c.relkind in ('r','p','v','m','S','f')
union all
select 'column',n.nspname,c.relname||'.'||a.attname,jsonb_build_object('position',a.attnum,'type',format_type(a.atttypid,a.atttypmod),'not_null',a.attnotnull,'identity',a.attidentity,'generated',a.attgenerated,'default',pg_get_expr(d.adbin,d.adrelid),'acl',a.attacl) from pg_attribute a join pg_class c on c.oid=a.attrelid join ns n on n.oid=c.relnamespace left join pg_attrdef d on d.adrelid=c.oid and d.adnum=a.attnum where a.attnum>0 and not a.attisdropped and c.relkind in ('r','p','v','m','f')
union all
select 'constraint',n.nspname,c.relname||'.'||k.conname,jsonb_build_object('definition',pg_get_constraintdef(k.oid,true),'validated',k.convalidated) from pg_constraint k join pg_class c on c.oid=k.conrelid join ns n on n.oid=c.relnamespace
union all
select 'index',n.nspname,c.relname,jsonb_build_object('definition',pg_get_indexdef(c.oid),'valid',i.indisvalid) from pg_index i join pg_class c on c.oid=i.indexrelid join ns n on n.oid=c.relnamespace
union all
select 'function',n.nspname,p.proname||'('||pg_get_function_identity_arguments(p.oid)||')',jsonb_build_object('definition',pg_get_functiondef(p.oid),'acl',p.proacl,'owner',pg_get_userbyid(p.proowner),'config',p.proconfig) from pg_proc p join ns n on n.oid=p.pronamespace where p.prokind in ('f','p')
union all
select 'type',n.nspname,t.typname,jsonb_build_object('kind',t.typtype,'owner',pg_get_userbyid(t.typowner),'acl',t.typacl,'base',format_type(t.typbasetype,t.typtypmod),'enum',(select jsonb_agg(e.enumlabel order by e.enumsortorder) from pg_enum e where e.enumtypid=t.oid)) from pg_type t join ns n on n.oid=t.typnamespace
union all
select 'trigger',n.nspname,c.relname||'.'||t.tgname,jsonb_build_object('definition',pg_get_triggerdef(t.oid,true),'enabled',t.tgenabled) from pg_trigger t join pg_class c on c.oid=t.tgrelid join ns n on n.oid=c.relnamespace where not t.tgisinternal
union all
select 'policy',schemaname,tablename||'.'||policyname,to_jsonb(p) from pg_policies p where schemaname in (select nspname from ns)
union all
select 'default_acl',coalesce(n.nspname,'GLOBAL'),pg_get_userbyid(d.defaclrole)||':'||d.defaclobjtype::text,jsonb_build_object('acl',d.defaclacl) from pg_default_acl d left join pg_namespace n on n.oid=d.defaclnamespace
union all
select 'event_trigger','GLOBAL',e.evtname,jsonb_build_object('event',e.evtevent,'enabled',e.evtenabled,'tags',e.evttags,'function',e.evtfoid::regprocedure::text,'definition',pg_get_functiondef(e.evtfoid)) from pg_event_trigger e
)
select kind,schema_name,name,definition from objects order by kind,schema_name,name;
