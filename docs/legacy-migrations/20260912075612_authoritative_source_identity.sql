-- A publisher can advertise distinct source IDs on one shared landing URL.
-- URL identity applies only to observations without an authoritative ID.
alter table radar.program_sources drop constraint program_sources_source_id_discovery_url_key;
create unique index program_sources_unidentified_url_uidx
 on radar.program_sources(source_id,discovery_url) where source_program_id is null;
