# StartupRadar V2 failure investigation and recovery

This runbook describes implemented local behavior. Hosted Supabase/Auth, official API credentials, GitHub dispatch and real Telegram delivery still require an operating exercise. Database access below is privileged; member clients use authenticated team-scoped APIs instead. No recovery step means that a source was successfully collected or a message was delivered.

## Before enabling production

Apply all migrations in filename order on the selected dedicated project. Verify authenticated users see only their own team profiles and cannot read Telegram IDs or administrative snapshots. Seed `sources.json`; distinguish enabled sources lacking credentials from disabled sources with documented route/policy limitations. Verify one real program's original notice, attachments, extracted requirements, profile version, deterministic eligibility and ranking trace.

Keep V1 active while V2 collects with delivery disabled. Use `radar.cli compare` on matched collection periods and investigate both systems' unique items, duplicates, eligibility review and source failures. Test V2 delivery with a separate intended test bot/chat before switching the original webhook. Record evidence across multiple runs; a green test suite is not a cutover gate by itself.

## Source or extraction failure

1. Read `/api/admin/health` and `/api/admin/failures`. Check the source attempt time, counts and typed error rather than interpreting zero parsed items as an empty program market.
2. For `MISSING_CREDENTIAL` or `AI_NOT_CONFIGURED`, configure the documented environment variable. For `ROBOTS_DENIED`, `ROBOTS_UNAVAILABLE`, `CAPTCHA`, `BLOCKED` or `UNAPPROVED_HOST`, investigate the public route/policy; never bypass it or indiscriminately widen host allowlists.
3. For document parse/size/type errors, inspect the retained filename, original URL, hash and extraction status. A scan/image or unsupported file may require manual evidence review; do not mark evidence complete because the HTML shell loaded.
4. Once the cause is resolved, use `python -m radar.cli run --kind INGEST --source VERIFIED_SOURCE_SLUG` or the admin retry action. This refreshes stored versions and team recommendations. Omitting `--deliver` means no external notification is planned/sent by that execution.
5. Verify the new source result and recommendation trace. Partial successes remain available independently of a failed source.

## Queued, uncertain or orphaned job requests

`/api/admin/health` includes recent job requests and schedule claims. `REQUESTED` means dispatch was requested, `RUNNING` means the workflow claimed its persisted ID, and `UNCERTAIN` means the dispatch outcome was not confirmed. A successful GitHub HTTP response does not prove job completion. A slow HTTP failure cannot overwrite a job's already-recorded progress or completion.

Inspect the actual GitHub Actions run before deciding whether to retry. If a request must be retired, an authenticated administrator can send `POST /api/admin/jobs/{job_id}/cancel` with `{"note":"Reason and investigation result"}`. The endpoint uses the same transaction advisory lock as `run_job`, rejects cancellation while any V2 job holds that lock, and accepts only REQUESTED/RUNNING/UNCERTAIN records. Completed jobs remain intact. It writes a CANCEL_JOB audit entry preserving the prior state/result, then marks the request CANCELLED. A delayed workflow carrying the cancelled ID exits without executing; repeated cancellation is idempotent.

This cancels the local request, not GitHub's workflow container. It does not undo completed ingestion or delete/cancel notification batches already created. Inspect those batches separately before retrying. Direct/manual jobs without a persisted request ID are protected by the job lock but are not cancelled through this endpoint.

A crashed TICK can leave a RUNNING schedule claim. Claims do not automatically replay, because delivery may have partly completed. Inspect the actual run and notification ledger, then issue a deliberate new manual job as appropriate. Do not delete schedule claims simply to force replay. Current health APIs expose them; automated dead-job paging and an explicit schedule-claim reconciliation UI remain future operating work.

## Telegram failures and uncertain receipts

`/api/admin/notifications` lists batches and items. PENDING is queued, SENDING is durably claimed before HTTP, DELIVERED requires a receipt, FAILED is a definite rejection, and UNCERTAIN needs investigation. An HTTP timeout is not proof of no delivery.

Use the existing admin recovery screen or `POST /api/admin/notifications/{batch_id}/recover` with an action and note:

- `RETRY_REJECTED`: requeue a definite rejection after resolving its cause.
- `CONFIRM_NOT_SENT`: requeue an uncertain/stale claimed batch only after an operator confirms it was not delivered.
- `CANCEL`: retire the batch without resending it.

SENDING must be at least 20 minutes old before recovery is accepted. Before each send, the application checks current program/profile versions, eligibility, deadline and subscription. A stale batch is cancelled conservatively; remaining valid opportunities may be deferred. PostgreSQL and Telegram do not share an atomic transaction, so an exactly-once external delivery guarantee is not claimed.

## Identity and duplicate review

Publisher IDs take priority over URLs. Two distinct IDs from the same source can share a landing URL and remain separate programs. Without a source ID, an observation uses its source/discovery URL identity. Across sources, a URL match also requires the same normalized title and organization and one unambiguous candidate; conflicting IDs from that publisher prevent merging. A confirmed existing source ID retains its program even if its URL changes to another notice's URL.

Shared URLs and fuzzy similarities can create review candidates. Review confirmation currently records the decision; it does not rewrite historical program/profile/notification foreign keys. Existing wrong merges from earlier versions are not automatically split by the identity migration. Inspect original snapshots before any corrective data migration.

The URL uniqueness constraint now applies only to observations without a source ID. Its upsert uses the same index predicate, following PostgreSQL's [partial unique index](https://www.postgresql.org/docs/current/indexes-partial.html) and [ON CONFLICT inference](https://www.postgresql.org/docs/current/sql-insert.html) semantics. Existing authoritative `(source_id, source_program_id)` uniqueness and all RLS policies remain enforced.
