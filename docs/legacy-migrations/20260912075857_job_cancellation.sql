alter table radar.job_requests drop constraint job_requests_state_check;
alter table radar.job_requests add constraint job_requests_state_check
 check(state in ('REQUESTED','RUNNING','SUCCESS','PARTIAL_SUCCESS','FAILED','UNCERTAIN','CANCELLED'));
