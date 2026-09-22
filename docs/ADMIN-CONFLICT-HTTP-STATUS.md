# Administrator conflicts return HTTP 409

## Scope and reason

The new forward migration `20260922143410_radar_admin_business_conflict_http_status.sql`
changes only the explicit business-conflict SQLSTATE from `40001` to `PT409` in:

- `public.gfc_radar_admin_set_operation(boolean,integer,text)`
- `public.gfc_radar_admin_set_visibility(text,integer,text)`
- `public.gfc_radar_admin_withdraw_briefing(uuid,text)`
- `public.gfc_radar_admin_restore_briefing(uuid)`

A stale version, an already hidden briefing, or an already restored briefing cannot
succeed by retrying the same request. Supabase documents that PostgREST 14 can retry
custom `40001` errors indefinitely and recommends a business-error code such as
`PT409`: [Supabase troubleshooting](https://supabase.com/docs/guides/troubleshooting/high-cpu-and-infinite-transaction-retries-when-using-custom-error-codes-in-rpc-functions-77326b).
Real managed testing of the related GFC settings contract exposed this transport
problem. The Radar verification below is isolated SQL testing, not a claim that
these four Radar RPCs were exercised against managed production services.

## Preservation and application order

Apply only this new migration after the existing
`20260917100000_radar_operation_visibility_withdrawal.sql` contract. Do not replay
historical migrations or the GFC test fixture copy. A prerequisite guard rejects
missing RPCs before any replacement, preventing accidental new PUBLIC grants.
`CREATE OR REPLACE` preserves function identity, owner and privileges. Each old
body is retained except its one error-code literal: authorization, locking,
validation, visibility, hide/restore rules and audit writes are unchanged. The
migration does not update rows or alter tables, identifiers, delivery records or
scheduler state. Native PostgreSQL serialization failures remain untouched.

Deploy the compatible GFC client before or in the same release window; it accepts
both `PT409` and legacy `40001` while retaining each operator-facing message.
This Radar change is separate from the four GFC administrator migrations
`20260922104911` → `20260922104914` → `20260922105013` → `20260922143039`.
Already applied Radar schedule/title/snapshot/coordinator migrations stay applied.
The new Radar migration does not enable the independent scheduler.

Before application, compare the four live RPC definitions with their known
contract, and capture function OID, owner, ACL, config and stored-row fingerprints.
After application, confirm each definition contains exactly one `PT409` and no
explicit `40001`; compare metadata and data fingerprints. No effectful production
RPC or delivery is needed for that verification. A schema-reload notification is
included. The migration uses a transaction and short lock/statement timeouts.

For a client rollback, keep this database correction: the previous client may
show a generic error, but restoring `40001` would restore the timeout defect.
If a future independent defect requires database rollback, use a reviewed forward
migration retaining `PT409`; never replay the old file or restore direct writes.

## Evidence and limits

- `npm run test:db`: existing database/RLS checks plus **24/24** Node tests passed.
- Five new tests verify exact definition-only change, metadata and row preservation,
  stale operation/visibility conflicts, repeated hide/restore conflicts, authorization
  rejection, and missing-prerequisite rejection. Failed commands create no second
  change or audit record, and existing delivered content remains unchanged.
- GFC `radar-control` and `radar-weekly-status` tests: **6/6** passed with the new
  fixture. Client handling covers both codes for all four commands.
- GFC fixture is an exact copy of this source SQL, for isolated testing only.
- Managed Radar HTTP/role testing and production application were not performed
  by this implementation. Isolated identity fixtures do not prove managed Auth.
- Other profile/program-review business-conflict paths were not changed by this
  bounded fix; they require a separate caller/contract review. No native engine
  serialization code is caught or remapped anywhere in this change.
