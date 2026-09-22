# Weekly scheduler reliability — deployable while disabled

The scheduler code and additive observation SQL can be deployed with the
coordinator disabled. Deployment alone does not install extensions, create a
cron job, provision a credential, or invoke collection or Telegram delivery.
Activation is a separate operational step and is not implied by code deployment.
The operator subsequently moved the production start target to Tuesday 09:00 Asia/Seoul
on 2026-09-22. The legacy workflow and its existing admin timetable were updated separately in
commit 0b2b9a2; this did not activate the independent coordinator. Its pending SQL/tests now use
09:00 as well. This is a start target, not a publication-completion deadline.

## Evidence and cause boundary

Read-only GitHub job/step records were matched to `worker_executions.owner.github_run_id`,
ingestion, briefing and official announcement records in the shared DB. All times below are KST.

| Stage | 2026-09-15 | 2026-09-22 |
| --- | --- | --- |
| Expected schedule | 15:00:00 | 15:00:00 |
| GitHub run created | 20:20:19 | 20:10:23 |
| Runner/job started | 20:20:23 | 20:10:27 |
| Collection command started | 20:20:37 | 20:10:41 |
| Durable worker started | 20:20:41.010 | 20:10:44.563 |
| Ingestion | Existing published issue reused | 20:10:49.612–20:31:00.285 |
| Publication | Existing ID/content preserved | 20:31:02.514; 51 items, revision 1 |
| Official delivery | No new send; prior NO_SUBSCRIBERS result | DELIVERED 20:32:34.541 |
| Durable worker finished | 20:20:49.381 SUCCESS | 20:32:38.556 SUCCESS |
| GitHub run finished | 20:20:54 success | 20:32:42 success |

The pre-creation delays are **5h20m19s and 5h10m23s**. Both created-to-runner gaps are four seconds.
This places the large delay before the collector, not in source performance or runner startup.
September 22 subsequently took approximately 20m11s to collect its bounded scope; it is a separate
duration. Ingestion persisted PARTIAL_SUCCESS with BOUNDED_WEEKLY_SCOPE and the worker completed
successfully. This is bounded collection completion, not proof of exhaustive collection.
The live GFC Notice page was also read in an existing authenticated browser session and showed the
09.21–09.27 article with 51 new items. No settings were saved.

Both run-commit workflows had the same Tuesday cron, default branch `main`, 60-minute job timeout,
`startup-radar-v2-state` concurrency group and `cancel-in-progress: false`.
The weekly cron replaced an hourly schedule at commit `2c43a531` on September 14; the September 15
workflow edit `5d897318` added source checks without changing the calendar.
Execution gates were satisfied for these observed runs; current GitHub variable values were not
independently readable and are not inferred from DB settings.

Confirmed: the late trigger/run creation caused the main publication delay. Plausible: GitHub's
documented schedule-service delays. Unconfirmed: GitHub's internal reason, queue depth or load for
these two events. General documentation is not incident-specific evidence.

Sources: [September 22 run](https://github.com/jey24960-sketch/startup-radar/actions/runs/35719968768),
[September 15 run](https://github.com/jey24960-sketch/startup-radar/actions/runs/34962741899),
[GitHub schedule limitations](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

## Chosen design

An existing Supabase database cron wakes every five minutes, checks the durable state, and queues
an asynchronous `pg_net` request to the existing GitHub workflow_dispatch path. Collection,
selection, publication, visibility and official-channel delivery still use the existing worker.
There is no new worker platform, broad scheduler framework or recommendation-system redesign.

| Alternative | Decision |
| --- | --- |
| Move GitHub cron away from minute zero | May reduce general load exposure, but does not remove schedule-service dependence. Insufficient alone. |
| Add another GitHub schedule/watchdog | Same schedule service; not independent failure protection. |
| Supabase pg_cron + pg_net + Vault → existing workflow | Selected: existing infrastructure, small state machine, durable correlation. |
| New external scheduler/worker service | Additional account, secrets and operations; not needed for this scope. |

This separates trigger generation from GitHub schedule service but still depends on Supabase,
HTTP and GitHub dispatch/runners. It does **not** guarantee an exact start minute.
Current production has Vault but not pg_cron/pg_net installed. Activation therefore requires two
extensions and a repository-scoped Actions-write credential stored in Vault, separately approved.
It uses existing service billing; this document does not promise zero added usage or cost.
No credential is placed in the frontend, repository, audit or dispatch response records.
The HTTP destination, repository, ref and workflow are fixed, not caller-controlled.

References: [Supabase pg_net](https://supabase.com/docs/guides/database/extensions/pg_net),
[GitHub workflow dispatch](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event).

## Durable contracts and preserved behaviour

- `weekly_schedule_requests`: one stable UUID for each Seoul Monday, exact Tuesday due time,
  optional atomic worker association, or an explicit paused-week suppression reason.
- `weekly_dispatch_attempts`: at most three attempts per request, ten minutes apart when no
  worker is claimed. Store response classification/status only, never HTTP headers/body/token.
- GitHub 204 means ACCEPTED, never worker/publication/delivery success. Lost responses and
  timeouts remain UNKNOWN; 408/429/5xx are retryable, other rejection stops automated retries.
  pg_net queues are unlogged and response retention is short; the durable ledger is authoritative.
- Tick and worker claim use existing advisory lock `782394202`. A claim transaction creates the
  durable worker and associates the request together. The worker validates the request, ISO Monday,
  current Seoul week and due time against the DB server clock before doing work. The same clock
  anchors publication. Old/future/mismatched requests do not collect, publish or send.
- Repeated request IDs do not rerun even after failed/uncertain execution. A legacy/manual active
  worker blocks dispatch. A previous-week unfinished owner is BLOCKED_RUNNING. No owner expires
  merely because it is old; explicit verified recovery remains necessary.
- Publication still uses its existing lock and `(week_start, publication_kind)` uniqueness.
  Published normal reruns keep the existing ID/content. Explicit revision and its audit are unchanged.
- Official delivery still claims PENDING → SENDING before HTTP and uses the original uniqueness
  ledger. UNCERTAIN/SENDING are never automatically reset. A missing valid delivery receipt is now
  classified UNCERTAIN rather than claiming success.
- Operator pause before claim suppresses that scheduled week, including if the worker observes a
  pause between cron ticks. Resume does not automatically backfill a suppressed week. Manual
  authorized weekly operation retains its existing semantics.
- Disabling the coordinator stops future dispatches, not already accepted/in-flight workers.
  Use the existing operation pause if queued workers must also be stopped before claiming.
- No public URL, briefing ID, image, publication window, member visibility, hide/restore operation,
  audit or source-selection rule is changed. No historical data is deleted or rewritten.

## Observation and recovery

`gfc_radar_admin_weekly_status()` retains every old response field and adds `schedule.runtime`.
It is admin-only and read-only; no browser role can run the coordinator or read private requests.
The GFC panel displays dispatch, collection, publication and delivery separately:

| Observation | Meaning and action |
| --- | --- |
| Before due / before activation week | Waiting, not success. |
| No runtime / cron not registered / heartbeat absent or ≥15m old | Unconfirmed or misconfigured; inspect scheduler. |
| Coordinator disabled | Supabase path unused; existing GitHub schedule remains unconfirmed. |
| HTTP accepted, no owner after 10m | Start delayed; same request gets bounded retries. |
| 3 attempts exhausted / permanent rejection | Operator intervention, no endless automated calls. |
| Worker RUNNING <60m / ≥60m | Running / long-running; no automatic restart. |
| FAILED / UNCERTAIN | Inspect actual worker and side effects before recovery. |
| PUBLISHED / DELIVERED | Separate persisted publication / delivery evidence. |

The admin view exposes missing execution/publication after the due time and missing/stale heartbeat.
It refreshes through the existing read path and explicit refresh; no outbound alert has been added
or sent. A screen that is never opened is not a proactive alerting guarantee. If proactive alerts
become operational policy, first use an existing operator channel, separately from the official
member publication channel, and review its recipient and delivery authority.

For a failed collection, inspect the Actions run, execution ledger and partial publication state;
use the existing `execution-status` / verified `recover-execution` only when necessary. Never infer
process death from elapsed time. A normal authorized current-week rerun reuses an existing issue.

For **publication success with definitive delivery failure**, a new privileged command prepares
the same announcement ledger for retry without dispatching or sending:

```text
python -m radar.cli recover-weekly-announcement --announcement-id UUID --note "Verified failure and operator reference" --confirm-not-delivered
```

It requires FAILED, no receipt/delivered_at, no active worker, same enabled official channel,
visible published WEEKLY and allowed visibility. The previous failure is audited before PENDING.
Then a separately authorized normal `weekly --deliver` reuses the published ID. SENDING,
UNCERTAIN and DELIVERED cannot use this reset. The current weekly command does not send an old
week after the Seoul week changes; do not change its week or ID as a recovery shortcut.

## SQL ownership, deployment order and cutover

Radar owns both new coordinator tables and the shared public Radar RPC. The GFC copy under
`tests/fixtures/radar-migrations/` is a test fixture only, never a second production migration.

### Safe release before an independent scheduling credential exists

The user authorized deploying the completed work on 2026-09-22. The title-only
release is `d9ed39e197bd1b36e0e5902c9e1620f0d84376bc`; the 09:00 calendar is
already in `0b2b9a2`. Preserve both. Title SQL was applied as ledger version
`20260922132845`; do not replay it because the source filename differs.

For this release, verify `RADAR_WEEKLY_SCHEDULER` is absent or `github`, retain
`RADAR_V2_ENABLED=true` and the existing delivery gate, and do **not** run either
operations script. Apply the following missing migrations explicitly, in order:

1. `20260922104947_admin_weekly_operation_snapshot.sql`
2. `20260922114649_weekly_dispatch_coordinator.sql`

Production application completed on 2026-09-22: source `20260922104947` maps to
ledger `20260922133441`, and source `20260922114649` maps to ledger
`20260922133449`. Do not reapply these sources or repair history just to match
filenames. Read-only postchecks found `enabled=false`, cron registration false,
zero requests/attempts, no pg_cron/pg_net extensions and zero active workers.
Briefing, item and announcement-ledger fingerprints stayed unchanged. No tick,
activation, collection or send was executed by this application.

The first historical snapshot has a 15:00 timetable; the coordinator wrapper
immediately overrides its timetable to the approved 09:00 without changing any
observed records. Apply both in the same deployment window before releasing the
GFC reader. The already-applied `20260922130546_weekly_execution_0900_kst.sql`
updates the separate control snapshot and must not be replayed. Check actual
definitions and ledger names before applying anything; never bulk-push the
historical migration directory to reconcile timestamp ordering.

After SQL, confirm `runtime_settings.weekly_scheduler.enabled=false`, the two
new tables are empty, no coordinator cron job exists, and the admin RPC returns
09:00 KST plus a disabled/unregistered runtime. Deploy the worker/workflow to
`main`, then the additive GFC reader. Legacy GitHub schedule remains Tuesday
09:00 KST. Manual calls with no scheduler request ID retain their old path and
do not query the new request tables. No collection or send is needed to verify
this inert deployment. Retain all new tables and existing ledgers on application
rollback; no database down migration is required while the coordinator is off.

Actual Supabase-to-GitHub invocation and four-week timeliness observation remain
activation gates. In particular, deploying these files is **not** evidence that
the five-hour scheduling issue has been eliminated. The only required user-side
credential step is provisioning an appropriately scoped GitHub Actions-write
secret through Vault; never paste the value in chat, source, shell arguments or
logs. Enable the independent path only after provider validation and reviewed
future-week cutover below.

### Independent scheduler activation

1. Preserve current branches and review diffs. Read-only preflight:
   `supabase/diagnostics/weekly-scheduler-preflight.sql`. Compare live function definitions and
   migration ledger with the intended dependency chain. The September 22 live DB did not yet
   contain `20260922104947_admin_weekly_operation_snapshot.sql`; it is a dependency from the
   separate admin work, not something to assume deployed. Historical repository migrations and
   the live ledger differ; never blindly replay the historical directory or repair the ledger.
2. In an approved isolated **Supabase** project, apply the reviewed prerequisites, then
   `20260922104947_admin_weekly_operation_snapshot.sql`, then
   `20260922114649_weekly_dispatch_coordinator.sql`. The latter creates empty constrained tables
   and an inert disabled setting; no data migration, extension installation, secret or cron job.
   Review for existing manually created names; halt on differences rather than merge/delete data.
3. Verify actual pg_cron/pg_net/Vault permissions and fixed dispatch destination in that approved
   environment. Use a nonproduction test workflow/credential under a reviewed test adaptation,
   never a production collection/send as a health check. This real provider test is not completed.
4. Apply only the reviewed forward migrations and deploy
   the compatible Python worker/workflow to `main`; then deploy the additive GFC reader. The old
   reader tolerates the added JSON key; the new reader tolerates the old RPC/no runtime. Existing
   manual worker calls need no new options. Old schema is not compatible with new scheduled IDs,
   hence no external dispatch before migration + worker availability.
5. Provision the narrowly scoped, expiring GitHub Actions-write credential through approved Vault
   tooling, named `startup_radar_github_dispatch`. Never paste it into this SQL or logs. Confirm
   GitHub `RADAR_V2_ENABLED=true`, intended `RADAR_V2_DELIVERY_ENABLED`, repository/workflow/default
   branch and absence of an active/uncertain owner. Do not broaden other project permissions.
6. Well before a **future** Tuesday due time, set `RADAR_WEEKLY_SCHEDULER=supabase`, then execute
   reviewed `supabase/operations/weekly-scheduler-activate.sql` with a future Monday and a change
   note. If activation fails, restore the GitHub mode promptly. Do not cut over near a due time.
   The script installs extensions, protects pg_net queues containing secret headers, checks Vault
   name presence, registers exactly one five-minute cron and enables the future week atomically.
   If the extensions were installed by another project since the preflight, re-review shared net
   permissions before applying the revokes. The script sends nothing immediately.
7. Read the admin RPC/cron execution records after the first tick: registered=true, recent heartbeat,
   correct future activation week. Do not interpret registration alone as successful HTTP/worker.
   The legacy cron remains in YAML as rollback fallback but its job gate is off in Supabase mode.
   Already queued old workflows may still run; durable ownership, stable publication and delivery
   ledgers protect the overlap. No forced cancellation or ledger deletion is needed.

The psql activation/disable scripts are **not automatically run migrations**. Neither has been
executed against production. A single migration failure rolls back its transaction. No historical
SQL is edited, no data cleanup is part of deployment, and no new external permission is presumed.

## Rollback

- Disable with `supabase/operations/weekly-scheduler-disable.sql` and an audit note; this updates
  only coordinator control and unschedules the matching job in the same database/user.
- Restore `RADAR_WEEKLY_SCHEDULER=github` (or its prior value) for future legacy schedule events.
  No old missed week is automatically replayed. Inspect the current owner before manual recovery.
- Keep new tables/ledgers and additive SQL. Do not drop shared extensions/Vault or erase attempts.
  If emergency queued-work prevention is needed, use existing operation pause first; it cannot
  cancel a worker already executing. Revoke/rotate the dispatch credential only through approved
  credential operations, accounting for pending HTTP queues.
- GFC can roll back independently because the response is additive. Python/workflow rollback
  must follow disabling external dispatch and draining/inspecting queued runs. Old code does not
  understand the new scheduler arguments. Do not reset publication/send state to facilitate rollback.

## Validation and remaining gates

Isolated tests exercise synthetic data/collectors/transports, not real collection or Telegram:

The disabled-release candidate was reverified after the 09:00 and title changes
against a fresh marked loopback PostgreSQL database with the complete current
migration chain. The selected publication/ownership/operation/scheduler suites
first passed 122 tests with six native-only cases skipped; rerunning the three
relevant files with `TEST_NATIVE_POSTGRES=1` passed all 45 tests, including those
six. These overlap: together they cover 128 distinct selected cases, not 167.
The DB security test, 19 PGlite coordinator/title tests, six webhook/workflow
tests and Python compilation also passed. No live source or Telegram call ran.

- PostgreSQL 17: existing weekly/broadcast/ownership/pause plus new scheduler regression 101/101;
  then new suite including two additional native races 24/24. These sets overlap; do not add them
  as 125 distinct tests. Native tick/tick, tick/claim, scheduled/manual and concurrent announcement
  calls produced one durable claim/publication/send. Commit-ack loss stays UNCERTAIN.
- PGlite new coordinator suite 14/14: default disabled, fixed target, accepted≠started, missing
  response and retry cap, rejected/retryable responses, pause suppression, long/failed owners,
  older-week blocking, Seoul boundaries, browser-role denial, RPC compatibility and read-only use.
  net/cron/Vault are synthetic stubs here; actual provider integration is not proven.
- Existing Radar DB security suite and Telegram worker suite pass; the new SQL suite is included
  in `npm run test:db`, used by existing CI. Python new suite is discovered by existing pytest CI.
- `tests/weekly_workflow_gate.test.mjs` evaluates the actual YAML gate for legacy,
  external and manual calls across enabled/disabled/unset variables. It executes
  the actual shell argument builder with a stub Python command, proving inputs
  containing spaces, newlines and shell-looking text stay literal. No worker or
  external request runs; the test is part of `npm run test:worker`.
- GFC unit/SQL/browser regression and final build results are recorded in the task's final report.
  Synthetic desktop/mobile screenshots show the status panel. Production Notice was read only.

On Monday or Tuesday before 09:00 KST, six positive scheduler-claim tests explicitly skip because
they enforce the real server clock. They all ran in the September 22 verification. Pure SQL clock
boundary tests remain deterministic throughout the week. This limitation is disclosed, not hidden
by allowing the production worker to accept a test clock.

Not executed: real pg_cron/pg_net/Vault-to-GitHub dispatch, GitHub mode changes, hosted runner
integration, external source/Telegram calls, production schema/permissions, cutover or rollback.
Those need a separately approved environment/operation. Docker/OCR deployment tests are outside
this schedule-only change and were not rerun locally.

After real provider validation and approved activation, observe **four consecutive weekly runs**:
first dispatch within five minutes of due, worker claim within ten minutes, one stable weekly
publication and at most one confirmed official send, no stale heartbeat or silent omission.
Measure publication duration separately; investigate no publication by the existing 60-minute
worker timeout and verify the UI indicates long-running/unknown rather than automatic restart.
These are proposed acceptance thresholds, not a guarantee or a newly imposed publication SLA.
Any missed start, duplicate or unreported missing record fails the observation gate. Local test
success alone cannot prove scheduler timeliness. The operator's follow-up establishes 09:00 as
the execution start target. No publication-completion deadline has been promised.
