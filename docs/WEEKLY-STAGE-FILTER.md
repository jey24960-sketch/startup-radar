# Weekly opportunity stage filtering (local implementation)

The GFC weekly article sorts the complete published item snapshot using the
existing `radar/stage.py` / `docs/WEEKLY-BRIEFING.md` order:
`STAGE_0` idea exploration → `STAGE_1` team/idea → `STAGE_2` landing/market
validation → `STAGE_3` MVP/PoC → `STAGE_4` registered business/corporation.
This is editorial suitability, not eligibility or a publication gate.

The detail RPC aggregates **all** items into one JSON response, without LIMIT or
OFFSET. The 20-row pagination and search in `gfc_radar_weekly_briefings` apply to
publications, not their items; they remain unchanged. No item pagination or new
item search was introduced. Stage changes select the complete loaded snapshot
synchronously; they cannot race another stage-filter request. Existing article
fetch cancellation still protects navigation and visibility refreshes.

Within a stage, existing relevance section priority and `display_order` are kept,
then `program_id` is the stable tie-breaker. In ALL, a multi-stage item uses its
earliest valid code; a specific filter uses membership in its valid codes. Items
appear once and keep the existing stage badges and restriction explanations.
Unknown codes are ignored; no valid code means Unspecified, last in ALL. Labels,
titles and eligibility text never become classification inputs.

## Additive read contract

`20260922150853_weekly_item_sort_identity.sql` adds `program_id` and `display_order`
to each returned item and adds an ID tie-breaker to the existing RPC aggregate.
`display_order` is currently unique within a publication; the ID tie-breaker is
defensive and independently tested in the client. The migration changes no stored
row, date, URL, snapshot, stage classification, delivery, grants or visibility
logic. Existing `require_published_read()`, PUBLISHED and not-withdrawn checks,
function identity/owner/ACL/config and old response fields stay intact.

Apply this Radar-owned migration once **before** deploying the GFC client. Compare
the live read function with the existing 20260917 definition first; do not overwrite
unreviewed drift. The copy in GFC `tests/fixtures/radar-migrations/` is for isolated
tests only and must not be applied separately. The old client ignores the new
fields. The new client tolerates the old array order during transition, but full
ID-based tie-breaking requires the additive contract. For a UI rollback, keep the
harmless extra fields and revert only the client. No stored-data rollback is needed.

## Verification

`npm run test:db` includes `tests/weekly_item_identity.test.mjs`: 65 items beyond
the feed page size, real isolated SQL, additive old-field equality, immutable
snapshot/delivery/audit comparison, function metadata preservation, existing role
visibility and hidden/draft exclusions. Synthetic fixtures obey the existing
item-count, unique display-order and publication timestamp constraints.

GFC adds `tests/weekly-items.test.js` and `e2e/weekly-stage-filter.spec.js` for all
five codes, stable ties, multiple/missing/invalid codes, complete-list filtering,
outer search/page coexistence, rapid changes, late article responses, loading,
errors, malformed responses, empty/reset and keyboard/mobile/desktop operation.

No production migration, collection, sending, commit, push or deployment was run.
Managed service and production UI validation of this new feature remain unrun.
