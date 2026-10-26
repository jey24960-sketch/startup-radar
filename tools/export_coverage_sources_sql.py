"""Render the approved source-coverage rollout without running SQL or HTTP."""
import argparse
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CHANGED_SOURCES={
    'weekly-naver-d2sf','weekly-unist-venture-notices',
    'weekly-korea-anam-programs','weekly-bizinfo-events',
    'weekly-postech-aif-notices','weekly-yonsei-notices',
    'weekly-koef-recruitment','weekly-asan-notices',
}

def render():
    rows=json.loads((ROOT/'weekly-direct-sources.json').read_text(encoding='utf-8'))
    payload=json.dumps([s for s in rows if s['slug'] in CHANGED_SOURCES],ensure_ascii=False,indent=2)
    return '''-- Approved 2026-10-27: source discovery expansion; no publication or send.
-- Generated from weekly-direct-sources.json by tools/export_coverage_sources_sql.py.
do $coverage$
declare proposed jsonb; previous jsonb; api record;
begin
  for proposed in select value from jsonb_array_elements($sources$'''+payload+'''$sources$::jsonb)
  loop
    select to_jsonb(s) into previous from startup_radar.sources s where slug=proposed->>'slug';
    insert into startup_radar.sources(slug,name,adapter,enabled,config)
    values(proposed->>'slug',proposed->>'name',proposed->>'adapter',
           (proposed->>'enabled')::boolean,proposed->'config')
    on conflict(slug) do update set name=excluded.name,adapter=excluded.adapter,
      enabled=excluded.enabled,config=excluded.config;
    insert into startup_radar.admin_audit(action,entity_id,detail)
    values('SOURCE_COVERAGE_EXPANSION',proposed->>'slug',jsonb_build_object(
      'reason','Approved direct publishers, event channel and verified linked pagination',
      'previous',previous,'applied_source',proposed));
  end loop;
  -- Preserve unrelated API options, IDs and source health history.
  for api in select id,slug,config from startup_radar.sources where adapter in ('KSTARTUP','BIZINFO')
  loop
    update startup_radar.sources set config=coalesce(config,'{}'::jsonb)
      || '{"weekly_detail_enrichment":true}'::jsonb where id=api.id;
    insert into startup_radar.admin_audit(action,entity_id,detail)
    values('SOURCE_DETAIL_ENRICHMENT_ENABLED',api.slug,jsonb_build_object(
      'reason','Read official HTML facts without AI; preserve API identity and source facts',
      'previous_config',api.config,'weekly_detail_enrichment',true));
  end loop;
end
$coverage$;
'''

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('output')
    args=parser.parse_args()
    Path(args.output).write_text(render(),encoding='utf-8')
