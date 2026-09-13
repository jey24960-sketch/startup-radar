-- Cover new-schema FK lookups identified by the hosted performance advisor.
-- No existing GFC table, index, policy or grant is changed.
begin;
set local lock_timeout='2s';
set local statement_timeout='30s';
create index evaluations_profile_fk_idx on startup_radar.eligibility_evaluations(profile_version_id,team_id);
create index evaluations_program_fk_idx on startup_radar.eligibility_evaluations(program_version_id);
create index batches_subscription_fk_idx on startup_radar.notification_batches(subscription_id);
create index items_program_fk_idx on startup_radar.notification_items(program_version_id);
create index items_recommendation_fk_idx on startup_radar.notification_items(recommendation_id,team_id);
create index items_run_fk_idx on startup_radar.notification_items(run_id);
create index items_subscription_fk_idx on startup_radar.notification_items(subscription_id,team_id);
create index items_team_fk_idx on startup_radar.notification_items(team_id);
create index duplicates_candidate_fk_idx on startup_radar.possible_duplicates(candidate_program_id);
create index change_events_program_fk_idx on startup_radar.program_change_events(program_id);
create index requirements_document_fk_idx on startup_radar.program_requirements(document_id,program_version_id);
create index snapshots_program_fk_idx on startup_radar.program_source_snapshots(program_id);
create index snapshots_version_program_fk_idx on startup_radar.program_source_snapshots(program_version_id,program_id);
create index programs_current_version_idx on startup_radar.programs(current_version_id,id);
create index recommendations_evaluation_fk_idx on startup_radar.recommendations(evaluation_id,team_id);
create index telegram_admins_team_fk_idx on startup_radar.telegram_admins(selected_team_id);
commit;
