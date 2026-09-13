# StartupRadar 2.0 implementation ledger

**Current shared-GFC staging update:** see SHARED-GFC-REPORT.md. Supabase project etvffzxqdgblvkfdikwl now has the startup_radar baseline and FK-index migrations. Existing GFC objects/data were verified unchanged. The earlier five-migration checkpoint below is historical; its migrations are archived and are not the hosted setup procedure.

Complete approved scope: V2-SPEC.md. Baseline audit: V1-AUDIT.md. Branch: feature/startup-radar-v2. Remote main is still c18f84048ddd08adca10d44b83692a1060d957cb; fetched again 2026-09-12. Production services have not been changed. V1 remains present. **This is a checkpoint, not completed V2 acceptance or cutover.**

## Current local implementation

- V1 typed analysis failures, delivered-item-only accounting, nonzero incomplete run status, Seoul clock, workflow concurrency and webhook authentication/update claims.
- Five PostgreSQL migrations with 28 RLS-enabled tables, profiles/program versions, source provenance, requirements, recommendation traces, outbox, message batches, runtime settings, job/cadence claims and audit.
- Five presets, independent team/product/business dimensions, unknown values, progressive profile updates and version conflict detection.
- Deterministic evidence-gated eligibility, dates and configurable ranking components. A failed condition cannot be overridden by AI/ranking.
- K-Startup/BizInfo adapters, RSS/Atom, configurable HTML, optional browser and explicit injected search interfaces. sources.json wires the initial registry into the CLI.
- Isolated document parsing (wall limit, Linux CPU/memory limits), visible failures, retained MIME/content hash/text and version-constrained evidence document links.
- FastAPI verified Supabase user authentication, team authorization, private member API, admin health/history/failures/duplicates/retry/trace/subscription/team APIs, static dashboard, invitation-only sign-in.
- Browser UI: five presets, team mode, filter/search, FACT/ELIGIBILITY/RECOMMENDATION details, citations including unknown-condition evidence, program history, optional profiles, progressive single-field input, member notification history, admin health/failure/retry/recovery/cadence/trace screens.
- Telegram V2 actual status/health, selected team, persistent stage updates, stop scheduling and persisted GitHub workflow dispatch. No actual external messages have been sent.
- Grouped weekly digest, exceptional high-fit and deadline planner; per-period/version keys, daily caps, immutable message batches, receipt mapping, current-state revalidation, explicit uncertain outcomes and audited manual recovery.
- CLI and hourly-wakeup V2 Actions workflow; daily collection/weekly digest/daily reminders use PostgreSQL cadence. Workflow and delivery both default disabled until repository variables enable them.

## Verification

- Final Python verification: 139 passed on native PostgreSQL 18.4, 1 third-party deprecation warning (Starlette/AnyIO BlockingPortal alias). Dependency check reports no broken requirements.
- Worker tests: 4 passed.
- Fresh migrations + team RLS/admin/anonymous denial assertions: passed with PGlite; native PostgreSQL profile/snapshot isolation tests also pass.
- Four native concurrency tests cover simultaneous version saves, exclusive jobs, cadence claims and parallel high-fit planners/senders. CI configuration provisions PostgreSQL 17; its GitHub execution is pending.
- Read-only V1/V2 comparison tests cover exact/alias matches, ambiguity, source failures, missing/mismatched collection periods and a database snapshot that neither sends nor writes recommendations.
- npm build: passed; self-contained bundled frontend.
- CLI help and Python compilation: passed.
- Browser fixture verification: initial stage 0 immediately shows two recommendations; detail separates facts/eligibility/ranking and quotes; entering fictional age 27 removes only the age missing-field requirement; admin UI visibly shows failed HWP extraction and unattempted source state.
- Windows browser verification exposed the system .js MIME mapping as text/plain; an explicit JavaScript response type fixes module loading and is regression-tested.
- Test collection initially imported a work/ scratch script and mutated the test bootstrap; pytest.ini now restricts collection to tests/. Duplicate bootstrap lines were removed. PGlite's default one-connection socket rejected briefly overlapping request/cleanup connections; the local harness now permits 10 multiplexed connections. The subsequent native PostgreSQL suite verifies real local lock concurrency; production pooler/crash behavior still requires deployment testing.
- Live public source: Korea University Sejong HTML yielded 13 notice links. First notice detail 547 characters; two HWP files successfully fetched and extracted at 3,595 and 1,924 characters. LIVE-SOURCE-CHECK.json preserves metadata. The old RSS contains only institution/about pages and is disabled. No AI/external Telegram call was involved in this live check.

## Acceptance criteria audit (spec section 24)

| # | Evidence and remaining gap |
|---|---|
| 1 | Preset-0 domain/API/browser flow verified with fictional notices; hosted invitation/login pending. |
| 2 | Versioned profiles and web progressive updates tested; team creation/membership API and bootstrap supplied. Full admin invitation UI pending. |
| 3 | Two real fixture teams yield ELIGIBLE vs INELIGIBLE through the API for the same program. Real notice cohort validation pending. |
| 4 | Unknown fields yield NEEDS_INFO; adding age removes only the corresponding missing field. |
| 5 | PRE_BUSINESS rejects registered-only requirements in unit tests. |
| 6 | Browser detail visibly displays quoted source evidence, including pending profile conditions. |
| 7 | Parse failures persist and appear in admin UI; isolated parser tests and live HWP sample supplied. |
| 8 | Multi-source exact identity/provenance integration tests pass; larger real dedup corpus pending. |
| 9 | Material deadline/update versions and update-alert idempotence tested. |
| 10 | Closed/date boundaries tested; stale queued deadline reminder cancels before sending. |
| 11 | Official adapters and registry/CLI/workflow wiring supplied; exact missing credentials documented. Live API success pending. |
| 12 | Korea Sejong HTML/HWP and KHU literal-navigation HTML acquisition demonstrated. Eleven legacy supplemental sources audited; 16 registry entries total, four enabled. Broader rollout remains pending. |
| 13 | Grouped weekly digest uses persisted team evaluations; confirmed/needs-info separated. Stubbed transport only. |
| 14 | /status reflects database run/source/scheduling state in tests. Hosted webhook pending. |
| 15 | /stage and web profile edits persist versions without Git changes; tested. |
| 16 | Admin health/failure/history UI implemented and browser checked. |
| 17 | Typed source/AI/document failures and partial ingestion tested; failed dispatch is visible in job history. |
| 18 | Worker update claims, outbox keys, daily cap and recovery tests pass; V2 Actions grouping/job lock/claims implemented. Production concurrency/crash validation pending. |
| 19 | Trace API links profile/program versions, evidence, scoring, notifications and immutable raw source/config/extractor snapshots. Binary archival and cross-source conflict resolution remain pending. |
| 20 | V1 preserved. No deployment/cutover/retirement performed. |

## Remaining work and known limitations

- Select and configure the dedicated Supabase project, apply migrations/advisors, verify actual Auth invitation/login, team isolation and pooler behavior. The earlier project-selection question remains unanswered; no unrelated connected project was modified.
- Configure official API credentials and validate real paginated responses. Legacy source inventory is audited; disabled adapters still require validated routes or policy/host availability before enabling. Search provider remains unconfigured; optional Playwright is not installed for deployment.
- Measure extraction completeness/semantic accuracy on a labeled Korean notice corpus, including complex OR/exceptions, dates, tables, images and scanned PDF. No claim of certified eligibility or nationwide coverage.
- Historical source snapshots are implemented. Remaining work includes cross-source conflict/trust resolution, normalization consistency and binary document archival/retention where needed.
- Validate production multi-process claims, crashes, timeouts and recovery. Externally exactly-once delivery is not guaranteed. Queued profile/program changes currently cancel the whole batch conservatively and may defer remaining opportunities.
- Membership and subscription management APIs exist; polished administrator invitation/team/subscription forms are not yet complete. Some condition/history labels remain internal keys. Large-catalog browsing currently filters in Python.
- Read-only V1/V2 comparison tooling is implemented; run live matched-period comparisons: V1-only/V2-only, duplicates, eligibility disagreements and failed sources. Define/observe acceptable reliability before switching the actual Telegram webhook or retiring V1.
- Complete hosted end-to-end deployment and operating runbook exercise. Build/tests alone are not acceptance.

## Handoff pointers

ARCHITECTURE.md: module/data flow, eligibility/ranking/delivery semantics, limitations.
LONGTAIL-SOURCE-AUDIT.json: actual supplemental source observations, disabled reasons and KHU adapter samples.
New migration: 20260912073008_source_snapshots.sql. New verification workflow: .github/workflows/test_v2.yml. No new production secret names in this checkpoint; TEST_NATIVE_POSTGRES is a local/CI verification flag.
V2-SETUP.md: environment, migrations, membership/bootstrap, web, Telegram, Actions and local fixture preview.
SOURCES.md: exact official contracts, adding sources and real long-tail evidence.
.env.example: names only, no credentials.


## Identity and recovery checkpoint

- Distinct publisher IDs now remain separate on a shared URL. Existing ID identity wins over conflicting URL matches; cross-source URL candidates require normalized title/organization agreement and uniqueness. Five new database regression cases pass. Existing wrongly merged historical records need reviewed repair and are not automatically split.
- Slow/rejected/timed-out GitHub dispatch responses cannot overwrite completed execution state. Three response-race tests pass.
- The admin job cancellation API retires queued/orphan/uncertain requests under the same execution lock, preserves an audit record, prevents late workflow execution, rejects non-admins/terminal jobs and refuses a concurrent live job. Direct API integration and native lock tests pass. No actual GitHub cancellation or Telegram send occurred.
- All 116 Python tests passed on native PostgreSQL; all five migrations and RLS assertions passed on a fresh PGlite instance. Python compilation and whitespace checks passed. The previous frontend build and four Worker checks remain valid because neither frontend nor Worker changed in this checkpoint.
- OPERATIONS.md provides the investigation/recovery runbook. Remaining gaps include production credentials/hosted Auth, real transport/workflow/crash exercises, full matched-period notice validation, complex extraction evaluation and cutover. Schedule-claim reconciliation and automated operator paging are still limited.


## Evidence/cutoff checkpoint

- Extraction and eligibility versions are 2.0.2. Unsupported OR output cannot create a hard failure; independent structured rules remain intact. Empty evidence, list/scalar operator mismatch and registration-date EXISTS are handled explicitly.
- Explicit Korean cutoff times are validated against full date/time citations. Date-only citations cannot hide nearby source times; unsupported formats and incomplete dates remain review failures. AI extraction is atomic with respect to the caller's official Program.
- Benefits require quoted source support. Quote presence checks do not guarantee semantic correctness or full section coverage.
- Full native PostgreSQL Python suite: 136 passed, one unchanged third-party deprecation warning. Compilation and whitespace checks passed. No database migration, frontend, Worker or dependency change in this checkpoint.
- Real previously acquired KHU detail: 2026-09-15 13:00 Seoul preserved; one second after cutoff is CLOSED. This validates deterministic parsing against source text, not live AI extraction accuracy.
- Current local V2 process environment was checked: DATABASE_URL, SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, ANTHROPIC_API_KEY, KSTARTUP_API_KEY, BIZINFO_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET and RADAR_GITHUB_TOKEN are unset. This does not assert that existing GitHub/production secrets are absent.
- Supabase project inventory was refreshed; no project is named StartupRadar. No unrelated project was changed. The project ID and web deployment target have been requested from the user. Live Auth/API/delivery/parallel validation remains blocked on actual setup, while local required work continues.


## Final local audit / external setup gate

The full specification audit is COMPLETION-AUDIT.md. During this audit, official date-only values were found to prevent finer source times from being applied. Program now records DATE/DATETIME/UNKNOWN precision, official adapters set DATE, and extraction 2.0.3 permits only same-day refinement. Three additional regressions pass. Browser display differentiates actual times from unknown/date-only precision; both states were inspected. The latest full native PostgreSQL run passes 139 tests; the frontend build and Python compilation pass.

The same outstanding project/host/runtime-credential selection has persisted across the recent checkpoints. Local fixes and documentation do not prove actual Auth, API/model response quality, Telegram receipt, workflow operation or matched-period V1/V2 reliability. The next required work is the six external gates in COMPLETION-AUDIT.md. No unrelated Supabase project, production deployment or external message was changed. The user has been asked for the dedicated project ID and web host; secret values should be configured in the execution environment rather than posted in chat.
