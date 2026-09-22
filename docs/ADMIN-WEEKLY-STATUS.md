# Weekly administrator status contract

The additive `public.gfc_radar_admin_weekly_status()` RPC is owned by **startup-radar**.
The GFC web repository consumes it through `src/lib/radarWeeklyStatus.js` and keeps an exact copy
of the migration under `tests/fixtures/radar-migrations/` for isolated integration tests.

Migration: `20260922104947_admin_weekly_operation_snapshot.sql`, created with the Supabase CLI.
Deployment is explicitly tracked in the shared database ledger; the presence of
this file alone does not mean it has been applied remotely.
On 2026-09-22 production applied this snapshot as ledger `20260922133441`, then
the disabled coordinator (`20260922114649` source) as `20260922133449`. Runtime
was verified disabled/unregistered with no new requests or attempts; stored
briefing/item/announcement fingerprints were unchanged. Do not reapply either
source to reconcile its CLI filename with the remote ledger timestamp.

## Observed facts, not inferred operation

The RPC reads the current Monday–Sunday Seoul week using the database clock. It returns the latest
weekly execution, the latest ingestion with `trigger_type='weekly'`, the week's WEEKLY publication
(not INITIAL_BASELINE), and the latest OFFICIAL_CHANNEL announcement record for that publication.
The ingestion and publication may refer to different attempts; the screen labels the latest collection
and the existing publication separately. A source recheck does not imply that an issue was revised.

Successful limited collection is identified only by the worker's persisted `BOUNDED_WEEKLY_SCOPE`
result for that ingestion ID. The web does not reimplement the collection-completeness classifier.
No 24-hour full-scan threshold, OCR result or personalized recommendation is used as a weekly health
requirement. Those existing diagnostics remain available in the advanced section.

The Tuesday 09:00 timetable is the current repository contract, not evidence that GitHub Actions ran.
The original snapshot migration retains its historical 15:00 definition; the coordinator
migration overrides scheduled_at/next_scheduled_at to 09:00 without editing migration history.
Both external execution and delivery gates remain `UNKNOWN`. An elapsed expected time without a
record is displayed as a need to check delay, not a claimed failed run. Publication does not imply
Telegram delivery. Only `DELIVERED` together with a delivery timestamp is displayed as delivered.
Existing delivery records remain visible even when the present settings prohibit a new send.

Access uses the existing `startup_radar.require_admin()` (`auth.uid()` plus GFC role). The RPC is
SECURITY DEFINER with an empty search path, fully qualified relations, no anon/PUBLIC execute,
and no direct table grants. It performs no writes, logging, collection, revision or message send.
The projection excludes chat IDs, payloads, delivery receipts, raw errors and worker owner details.
It reuses `admin_control_snapshot()` without changing the existing CAS/audit/visibility contracts.

## Deployment preflight and sequence

For the user-authorized disabled-coordinator release, follow the exact two-migration
sequence in [the scheduler runbook](WEEKLY-SCHEDULER-RELIABILITY.md#safe-release-before-an-independent-scheduling-credential-exists).
Do not deploy the historical snapshot alone and show its former 15:00 timetable.

1. Inspect the target migration history and compare the live definitions/columns against the repository.
   Required: the operator-control migration through `20260917100000`, `require_admin()`,
   `admin_control_snapshot()`, worker_executions.result, weekly publication kind/withdrawal columns,
   and official-channel announcement target_kind. Confirm `public.my_role()` still uses GFC roles.
   Do not repair unrelated historical migration version differences by replaying old migrations.
2. Confirm the timetable remains Tuesday 00:00 UTC in the production workflow. If it changed,
   update the documented timetable before showing a derived next expected time. No gate value may
   be inferred from the stored runtime flags.
3. Apply **only** the missing Radar-owned snapshot migration, immediately followed by
   `20260922114649_weekly_dispatch_coordinator.sql`, after their prerequisites. Keep the
   coordinator disabled. Do not apply the GFC fixture copies as second migrations.
   No content backfill or data transfer is needed.
4. Verify the function in a read-only transaction with synthetic/staging identities: admin succeeds;
   member, external and anonymous callers fail; no new table privilege is present; no secret fields
   are returned. Verify no audit rows or worker/delivery records are created by the read.
5. Deploy the compatible GFC web update. If it precedes the database, the status panel explicitly
   reports that the new read is unavailable; the existing operation controls and advanced health RPC
   remain usable. Verify desktop/mobile, missing records, failures, pause, existing delivery,
   withdrawal, and all three public visibility modes.

GFC's other administrator migrations are independent of this function. Their own ordering and
rollback instructions still apply; do not assume applying this migration applies those changes.

## Rollback and preservation

The snapshot migration creates one function; the coordinator subsequently wraps
it with an additive runtime projection. Restore the previous web build first if
reverting the feature. Leave the unused read-only functions and disabled
coordinator in place. Do not remove the base function while its wrapper depends
on it, drop tables, restore old control functions, delete runtime settings, reset
revisions, or remove audit rows.
All original collection, publication, withdrawal and Telegram ledger data remain untouched.

## Validation

GFC `tests/radar-weekly-status.test.js` executes the real mirrored migrations in isolated PGlite,
including a read-only transaction and an admin/member/anon permission check. Existing
`tests/radar-control.test.js` preserves CAS, central visibility, audit and soft-withdrawal regression
coverage. `e2e/radar-control.spec.js` additionally covers more than 50 publications, current-page
hide/restore, public focus/retry refresh, unknown probe errors and desktop/mobile weekly cards.
These tests do not connect to production or send messages. CI Postgres remains the authoritative
cross-process concurrency environment; this read-only RPC adds no new concurrent write behavior.
