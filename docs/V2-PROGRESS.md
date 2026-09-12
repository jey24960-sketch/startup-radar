# StartupRadar 2.0 implementation ledger

Complete scope: V2-SPEC.md (the original user-provided specification, unabridged).
Baseline audit: V1-AUDIT.md, written before implementation against c18f840.
Branch: feature/startup-radar-v2. Remote main/deployed V1 unchanged.

## Verified checkpoint — 2026-09-12

- V1 analysis uses typed SUCCESS/PARTIAL_SUCCESS/FAILED results, valid empty is distinct from error; delivery records accepted programs only, leaves undisplayed tail pending; incomplete runs exit nonzero; Actions concurrency added; business dates use Asia/Seoul.
- V1 webhook bridge validates secret, authorizes admin and stores update claims in a Durable Object. Deployment/binding/secret setup not performed. Claims avoid repeat dispatch; external-call ambiguity remains explicit.
- PostgreSQL migration created with Supabase CLI. All 23 radar tables have RLS. Local PostgreSQL engine tests validate own-team read/update, cross-team denial, non-admin operational privacy, anonymous denial, and rejection of self-granted admin.
- Repository tests verify profile versions, cross-source provenance, stable identity on source ID/URL changes, material deadline versions and ambiguous duplicate review relationships.
- Domain schemas preserve independent team/product/business dimensions and UNKNOWN. Five presets implemented; preset 0 needs no optional information; presets preserve explicit data. Evidence-driven deterministic eligibility and Seoul dates tested.
- Source interfaces, official K-Startup/BizInfo adapters (verified official contracts), RSS/Atom, HTML, browser and injected search architecture implemented. Public/live source validation and complete registry pending. Search has no concrete deployment provider yet.
- HTML/PDF/HWP/HWPX/DOCX extraction and typed failures implemented; resource-isolated parsing still pending.
- Schema-validated, exact-quote-checked AI extraction implemented. No production API calls made; semantic extraction quality not yet measured on real notices.
- Source-isolated ingestion persists runs/results and keeps successful sources when another fails.
- Deterministic ranking, evaluation trace persistence and initial PostgreSQL notification outbox implemented. Reminder duplicate planning and partial delivery tested. Telegram V2 is not production-ready yet.

## Test evidence

- `.venv/Scripts/python -m pytest -q` with explicit TEST_DATABASE_URL: 55 passed (includes PostgreSQL repository/ingestion/notification integration).
- `node --test tests/worker.test.mjs`: 4 passed.
- `node tests/database.test.mjs`: migrations and RLS assertions passed on a fresh PGlite PostgreSQL engine.
- `python -m compileall -q radar core main.py`: passed.
- `python main.py --help`: works without service credentials.
- No actual Telegram messages, production database migrations, hosted Auth checks, web build or deployment tested.

The local PGlite socket bridge encountered a protocol error after an invalid SQL parameter type during development. The SQL parameter was explicitly cast, the corrupted test server was stopped and restarted, and the full repository tests then passed. This is a local test-engine limitation, not a production reliability claim.

## Milestone state

1. Audit + V1 reliability: implemented/tested locally; deployment validation pending.
2. Supabase persistent layer: schema/repository locally tested; hosted target and migration pending.
3. Canonical schema: implemented/tested foundation; complete trace integration still being extended.
4. Official APIs: adapters written, fixtures pass; wiring/credentials/live validation pending.
5. Long-tail/documents: implemented/tested foundation; live source registry, parser isolation and real document corpus pending.
6. Requirements/eligibility: core implemented/tested; real extraction quality and complex-rule validation pending.
7. Profiles/presets: core implemented/tested; authenticated progressive web flow pending.
8. Recommendation/Telegram V2: initial core/outbox implemented; digest grouping, stale queued-item revalidation, retry/admin recovery, cadence configuration and additional alert/update tests pending.
9. Web/source health: persistence implemented; authenticated web/API and all required member/admin screens pending.
10. Parallel comparison/cutover: not started. V1 retained.

## Acceptance criteria audit (spec section 24)

1. Preset-0 domain behavior proved; immediate authenticated browser flow NOT YET implemented.
2. Structured profile update/version repository proved; user interface pending.
3. Same requirement gives different team outcomes in unit tests; real program UI demonstration pending.
4. Unknown attributes -> NEEDS_INFO proved in unit tests.
5. Registered-only requirement rejects PRE_BUSINESS proved.
6. Evidence preserved in rule/evaluation models; user-facing display pending.
7. PDF/HWP/HWPX failure retained in tests; admin failure screen pending.
8. Cross-source provenance/dedup integration proved; live comparison pending.
9. Material updates create versions integration proved.
10. Deterministic closed-date filtering tested; complete dashboard/delivery flows pending.
11. Official adapters implemented from primary contracts; runtime registry/credential setup and live response validation pending.
12. RSS/HTML architecture demonstrated by fixtures; live non-API demonstration pending.
13. Notification planner uses real stored team evaluations in tests; finished weekly digest UX and delivery validation pending.
14. V2 runtime /status NOT YET implemented; existing V1 status remains legacy.
15. V2 profiles persist without Git commits; runtime Telegram /stage and web integration pending.
16. Source health database results verified; admin UI pending.
17. Failed source/AI states explicit and partial ingestion tested; full UI reporting pending.
18. V1 workflow concurrency + update claims + outbox unique keys tested; V2 scheduler and stale/crash recovery pending.
19. Profile/program versions/evaluations/components/outbox are linked; complete reconstruction screen/export pending.
20. V1 remains present and runnable; no retirement/cutover performed.

## Immediate next work

- Complete source registry and command-line ingestion; verify a legitimate live public source without bypassing robots/challenges.
- Tighten foreign keys for notification subscription/team and evidence-document linkage; add schema constraints/indexes and tests.
- Revalidate queued notification eligibility/current version just before delivery, group weekly digest and expose FAILED/UNCERTAIN recovery without blind resend. Add high-fit/material-update tests and configurable frequency limits.
- Implement authenticated FastAPI web/API, Supabase invitation/member handling, progressive profiles, program facts/eligibility/recommendation views and admin health/history/duplicates/retry.
- Implement real Telegram V2 runtime commands and scheduling, then full acceptance/end-to-end tests and parallel-run report.
- Finish architecture/deployment/privacy/failure documentation, live validation and handoff. Do not declare completion based on this checkpoint.

## External dependencies

Supabase project selection requested asynchronously; no matching dedicated project identified, and no unrelated project mutated. KSTARTUP_API_KEY, BIZINFO_API_KEY and search-provider deployment configuration still required. V2 Auth, Telegram/subscription, Worker and workflow environment setup pending. Full completion remains UNPROVEN.
