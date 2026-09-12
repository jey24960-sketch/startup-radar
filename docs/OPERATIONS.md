# StartupRadar V2 failure investigation and recovery

The current deployment uses the existing GFC Supabase project `etvffzxqdgblvkfdikwl`, the private `startup_radar` schema, GFC member UI and a Python batch worker. A hosted Python HTTP API is not required. Source-to-Supabase-to-GFC operation and approved Telegram connection/digest delivery have been exercised; full role, reminder and cutover acceptance remains open. See [the current goal](GFC-OPERATING-GOAL.md), [endpoint decisions](PYTHON-API-DECISION.md), [Telegram ledger validation](TELEGRAM-LEDGER-VALIDATION.md) and [extraction limitations](EXTRACTION-SEMANTIC-REVIEW.md).

Database operations below are privileged operator actions. GFC members use authenticated Supabase RPC with member/team authorization. Python `/api/...` routes mentioned below are retained optional administrator/development capabilities; do not assume they are deployed on the GFC domain or that GFC implements their recovery screens. No recovery step alone proves successful collection or delivery.

## Before enabling production

Inspect applied migration history on the existing shared GFC project and review only pending migrations against its current schema. Do not provision a dedicated project or replay local fixtures. Verify authenticated members see only authorized team profiles and cannot read Telegram IDs or administrative snapshots; authentication alone does not establish membership. Compare stored source configuration with `sources.json` before any selective update: blindly reseeding can overwrite approved routes and enabled states. Distinguish missing credentials from documented route/policy limitations. Verify real notices, attachments, extracted requirements, profile versions, deterministic eligibility and ranking traces.

Preserve V1 code/workflows and rollback ability while V2 collects with delivery disabled. V1's schedule was observed `disabled_inactivity`; that does not authorize silently enabling it. Use `radar.cli compare` on matched collection periods and investigate both systems' unique items, duplicates, eligibility review and source failures. Use the user-approved existing Telegram test recipient and the documented scoped prepare/deliver validation flow. No webhook switch is needed for that test. Record evidence across multiple runs; a green test suite is not a cutover gate by itself. V2 collection and delivery schedules remain disabled until the goal's live acceptance and cutover review are satisfied.

## Stored member result reuse

`python -m radar.cli run --kind REFRESH` recomputes only stale/missing stored member results under the global V2 job lock. It performs no ingestion, AI call or Telegram delivery. Its result reports `computed`, `reused` and `scopes`. The cache checks program version, profile version and snapshot, Seoul evaluation day, configured ranking weights, presets and evaluator/ranking versions. A current-day unchanged rerun in a new process should report zero computed results. The job still reads cache rows and updates operational calculation state; zero recomputation does not mean zero database traffic.

Cache validity is fetched once for each bounded page of at most 100 versions in one scope, using parameterized UUID-array membership and the same profile/day/generation predicates. It no longer performs a separate network query for every cached result. If the Seoul day changes inside a page, the page's validity is fetched again for the new date. Pages and scopes remain isolated, and only invalid/missing rows are recomputed. This follows PostgreSQL's [array comparison semantics](https://www.postgresql.org/docs/current/functions-comparisons.html#FUNCTIONS-COMPARISONS-ANY-SOME). Historical versions and changed team profiles still incur work; connection setup, reads and per-result writes remain potential latency drivers.

Profiles serialize the set-valued `assumed_fields` in sorted order. Otherwise Python hash randomization changes the JSON array order across workers and falsely invalidates identical preset snapshots and profile cache keys. Old snapshots remain readable; the first refresh may replace differently ordered preset snapshots once. User profiles and profile history are not rewritten to normalize arrays. Profile changes, new program versions, a new Seoul day or changed calculation configuration still require fresh evaluation. Historical program versions remain evaluated for explicit history views; `reused` is a result-row count, not an opportunity count.

## Source or extraction failure

1. Open the GFC Radar administrator health view for its safe source/job projection. More detailed `/api/admin/health` and `/api/admin/failures` routes belong to the optional Python administrator API. Check the source attempt time, counts and typed error rather than interpreting zero parsed items as an empty program market.
2. For `MISSING_CREDENTIAL` or `AI_NOT_CONFIGURED`, configure the documented environment variable. For `ROBOTS_DENIED`, `ROBOTS_UNAVAILABLE`, `CAPTCHA`, `BLOCKED` or `UNAPPROVED_HOST`, investigate the public route/policy; never bypass it or indiscriminately widen host allowlists.
3. For document parse/size/type errors, inspect the retained filename, original URL, hash and extraction status. A scan/image or unsupported file may require manual evidence review; do not mark evidence complete because the HTML shell loaded.
4. Once the cause is resolved, use `python -m radar.cli run --kind INGEST --source VERIFIED_SOURCE_SLUG` in the configured privileged batch environment, or the optional Python administrator retry action if separately available. This refreshes stored versions and team recommendations. Omitting `--deliver` means no external notification is planned/sent by that execution.
5. Verify the new source result and recommendation trace. Partial successes remain available independently of a failed source.

## Queued, uncertain or orphaned job requests

`/api/admin/health` includes recent job requests and schedule claims. `REQUESTED` means dispatch was requested, `RUNNING` means the workflow claimed its persisted ID, and `UNCERTAIN` means the dispatch outcome was not confirmed. A successful GitHub HTTP response does not prove job completion. A slow HTTP failure cannot overwrite a job's already-recorded progress or completion.

Inspect the actual GitHub Actions run before deciding whether to retry. If a request must be retired, an authenticated administrator can send `POST /api/admin/jobs/{job_id}/cancel` with `{"note":"Reason and investigation result"}`. The endpoint uses the same transaction advisory lock as `run_job`, rejects cancellation while any V2 job holds that lock, and accepts only REQUESTED/RUNNING/UNCERTAIN records. Completed jobs remain intact. It writes a CANCEL_JOB audit entry preserving the prior state/result, then marks the request CANCELLED. A delayed workflow carrying the cancelled ID exits without executing; repeated cancellation is idempotent.

This cancels the local request, not GitHub's workflow container. It does not undo completed ingestion or delete/cancel notification batches already created. Inspect those batches separately before retrying. Direct/manual jobs without a persisted request ID are protected by the job lock but are not cancelled through this endpoint.

A crashed TICK can leave a RUNNING schedule claim. Claims do not automatically replay, because delivery may have partly completed. Inspect the actual run and notification ledger, then issue a deliberate new manual job as appropriate. Do not delete schedule claims simply to force replay. Current health APIs expose them; automated dead-job paging and an explicit schedule-claim reconciliation UI remain future operating work.

## Telegram failures and uncertain receipts

`/api/admin/notifications` lists batches and items. PENDING is queued, SENDING is durably claimed before HTTP, DELIVERED requires a receipt, FAILED is a definite rejection, and UNCERTAIN needs investigation. An HTTP timeout is not proof of no delivery.

In the optional Python administrator interface, use its recovery screen or `POST /api/admin/notifications/{batch_id}/recover` with an action and note. These recovery commands are not currently a GFC member RPC feature:

- `RETRY_REJECTED`: requeue a definite rejection after resolving its cause.
- `CONFIRM_NOT_SENT`: requeue an uncertain/stale claimed batch only after an operator confirms it was not delivered.
- `CANCEL`: retire the batch without resending it.

SENDING must be at least 20 minutes old before recovery is accepted. Before each send, the application checks current program/profile versions, eligibility, deadline and subscription. A stale batch is cancelled conservatively; remaining valid opportunities may be deferred. PostgreSQL and Telegram do not share an atomic transaction, so an exactly-once external delivery guarantee is not claimed.

## Identity and duplicate review

Publisher IDs take priority over URLs. Two distinct IDs from the same source can share a landing URL and remain separate programs. Without a source ID, an observation uses its source/discovery URL identity. Across sources, a URL match also requires the same normalized title and organization and one unambiguous candidate; conflicting IDs from that publisher prevent merging. A confirmed existing source ID retains its program even if its URL changes to another notice's URL.

Shared URLs and fuzzy similarities can create review candidates. Review confirmation currently records the decision; it does not rewrite historical program/profile/notification foreign keys. Existing wrong merges from earlier versions are not automatically split by the identity migration. Inspect original snapshots before any corrective data migration.

The URL uniqueness constraint now applies only to observations without a source ID. Its upsert uses the same index predicate, following PostgreSQL's [partial unique index](https://www.postgresql.org/docs/current/indexes-partial.html) and [ON CONFLICT inference](https://www.postgresql.org/docs/current/sql-insert.html) semantics. Existing authoritative `(source_id, source_program_id)` uniqueness and all RLS policies remain enforced.
