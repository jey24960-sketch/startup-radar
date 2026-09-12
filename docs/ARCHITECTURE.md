# StartupRadar 2.0 architecture and limits

Status: local implementation under validation. V1 remains the production baseline. This document describes V2 source code, not an assertion that hosted services are deployed or accepted for cutover.

```text
Hourly GitHub Actions wake-up / dashboard / Telegram admin command
    -> persistent job request + Seoul cadence claims + job lock
    -> source registry
         K-Startup / BizInfo APIs
         RSS / Atom / HTML notices
         optional explicit search provider / legitimate browser rendering
    -> discover candidates with source IDs and URLs
    -> bounded HTTPS detail/document fetch (allowlist, robots)
    -> isolated PDF / HWP / HWPX / DOCX / HTML text extraction
    -> strict, quoted-evidence AI requirement extraction
    -> PostgreSQL canonical programs + immutable versions + evidence
    -> deterministic eligibility against a versioned team profile
    -> separate configurable recommendation ranking
         -> authenticated FastAPI dashboard: FACT / ELIGIBILITY / RECOMMENDATION
         -> weekly / exceptional high-fit / deadline notification planner
              -> persisted single-message batches
              -> revalidate current team/program/subscription/date
              -> Telegram receipt, definite rejection, or uncertainty

Supabase Auth -> validated user -> team membership / administrator authorization
PostgreSQL RLS -> team-scoped private data; administrator-only operations
Source runs, document failures, jobs, batches, and trace history -> admin dashboard
```

## Code boundaries

| Module | Responsibility |
|---|---|
| `radar/models.py` | Strict normalized models, independent team/product/business dimensions, five presets |
| `radar/adapters/` | Discovery and source-specific detail normalization |
| `radar/http.py` | Public HTTPS allowlist, DNS checks, robots, redirect/size/time limits |
| `radar/documents.py`, `document_worker.py` | Attachment metadata, signatures, bounded isolated text extraction |
| `radar/extraction.py` | AI-to-schema conversion and verbatim evidence checks |
| `radar/database.py` | Transactional profiles, provenance, deduplication, program versions |
| `radar/eligibility.py`, `dates.py` | Deterministic conditions, Seoul business dates and deadlines |
| `radar/recommendations.py` | Ranking components and persistent evaluation/recommendation trace |
| `radar/notifications.py` | Idempotent planning, message batches, delivery states and audited recovery |
| `radar/scheduler.py`, `cli.py`, `jobs.py` | Cadence, claims, explicit workflow dispatch and command-line execution |
| `radar/auth.py`, `services.py`, `web.py` | Verified sessions, authorization and member/admin API |
| `radar/telegram.py` | Real `/status`, persistent `/stage`, workflow `/run`, runtime `/stop` |
| `web/src/app.js` | Lightweight dashboard; built with esbuild into `web/static/app.js` |

## Eligibility semantics

Presets initialize useful assumptions but preserve explicit input. Preset 0 needs no age, region, university or other optional data. Preset 3 never infers registration. Preset 4 permits either sole proprietor or corporation while leaving product stage independent. Previous preset assumptions are removed when switching presets.

Each requirement has a whitelisted key, operator, value, mandatory/certain flags and evidence entries: source/document ID, section, quote, method, confidence and verified flag. Operators: EQ, NEQ, IN, NOT_IN, GTE, LTE, RANGE and EXISTS. Requirements currently form a conjunction of mandatory conditions. Complex cross-field OR/exception clauses must remain uncertain; do not flatten them into an incorrect AND.

1. One confirmed mandatory failure yields INELIGIBLE, even if other evidence is missing.
2. Inadequate evidence yields UNVERIFIABLE if no confirmed failure exists.
3. Unknown required profile values yield NEEDS_INFO when source evidence is otherwise sufficient.
4. ELIGIBLE requires all represented mandatory conditions to be satisfied and adequate evidence.

Unknown is not false. Age bands are conservative: a band partly satisfying a restriction still needs information. Business age is computed against the evaluation date when registration date is known. ELIGIBLE describes the represented evidence, not an official guarantee of acceptance. Ranking cannot override a failed condition.

## Ranking

Default weights: product stage 25, profile match 20, preferred support type 15, benefit 10, global relevance 10, application runway 10, evidence completeness 10. Database runtime settings can configure weights. Components and exact weights are stored with each recommendation, along with provider/model and prompt/schema versions. The current provider is deterministic; explanations are templates, not generated strategic advice.

Only ELIGIBLE and NEEDS_INFO programs enter ranking. CLOSED/UNKNOWN dates and general policy loans, generic SME financing and generic R&D are excluded from recommendations. UPCOMING programs may be browsed as recommendations; notifications require OPEN. Benefit scoring currently uses information presence rather than expected monetary value. Global relevance, sector matching and semantic relevance need calibration against real GFC decisions.

## Identity and traceability

Authoritative source IDs and normalized exact URLs identify existing programs. Fuzzy matches create possible-duplicate relationships for review; confirming a relationship does not yet merge records. Material changes create new versions and NEW/UPDATE events. The first referenced attachment also has a version-constrained relational FK; all quote references retain content hashes. Different source records are preserved.

The admin trace endpoint connects recommendation -> evaluation -> profile version + program version -> original text and document evidence -> provenance -> notification receipt. Limitations: source metadata is currently updated in place in `program_sources`; it does not independently preserve every historical API envelope. Program versions preserve normalized facts and original detail text. No raw attachment binary archive/object storage is configured. Text and hashes are retained.

## Delivery semantics

Weekly digests select up to five items per subscription and week. The summary separates confirmed eligible from additional-information-needed items. The same selected set is not expanded by repeated weekly requests. Multiple items share one batch only if they fit one Telegram message; receipts mark only that batch's contents delivered. Exceptional high-fit alerts default to two items daily, score >= subscription threshold (90 by default), ELIGIBLE, at least three days left, and a new/material version within seven days. D-7 and D-3 reminders are configurable per subscription.

PENDING -> SENDING is committed before the HTTP call. Confirmed Telegram receipt -> DELIVERED. Definite rejection -> FAILED. Network/ambiguous server results -> UNCERTAIN. There is no automatic retry of uncertain delivery. An administrator must record that delivery did not occur before requeueing. SENDING batches cannot be recovered until at least 20 minutes have elapsed. This is duplicate-resistant delivery, not a claim of mathematically exactly-once external messaging.

Queued batches are cancelled if profile version, current notice version, relevant eligibility, deadline or subscription state changed. Cancellation is conservative: it may defer still-valid items until the next notification cycle. No atomic transaction spans PostgreSQL and Telegram; a small change-between-check-and-send window remains. A crash may leave RUNNING/SENDING state requiring investigation. Retention, dead-job alerting and production concurrency testing remain required.

## Acquisition and operational limits

- Registered-source success rate measures the last result of configured active sources. It is not nationwide opportunity coverage.
- Initial active registry: K-Startup, BizInfo, verified Korea University Sejong HTML notices. API credentials and live API response validation remain pending.
- The Korea RSS endpoint currently exposes two institutional pages, so it is disabled. Live HTML discovery found 13 notice links and extracted two HWP documents; this is a single-source sample, not a quality or coverage benchmark.
- HTML discovery visits one configured list. Older archive pagination and conversion of all V1 long-tail sources remain pending.
- Search is disabled until an explicit provider is injected. Browser acquisition needs separately installed Playwright/Chromium; it is not a challenge bypass.
- File limit 20 MB, archive expansion 40 MB, 500 PDF pages, extracted text 1,000,000 characters. Parser subprocess wall limit 25 seconds; Linux additionally applies 20-second CPU / 768-MB address-space limits. Windows lacks the Linux process memory limit.
- Scanned PDF OCR, encrypted/protected HWP, complex tables, images and layout-dependent semantic extraction are not comprehensively supported. HWP control codes can affect text quality.
- AI accepts up to 120,000 evidence characters; larger evidence is flagged for review. Quote existence does not prove semantic correctness or that all mandatory clauses were extracted. Real labeled-notice evaluation and human review remain essential.
- Host allowlists require maintenance for legitimate redirects/attachments. DNS is checked before requests, but production network isolation should also prevent DNS-rebinding/private-egress risks.
- Browse currently loads candidate rows and filters/ranks in Python. Large catalogs need database pagination/filtering, indexes and caching strategies.
- Supabase hosted Auth/login, invitations, PostgreSQL deployment, real Telegram delivery, workflow operation and V1/V2 parallel cutover are not yet validated.


## Historical observations and comparison checkpoint

The third migration adds `program_source_snapshots`, an append-only application path with version-constrained source metadata, configuration, detail hashes and extraction model/schema/status. Admin trace returns those observations. Repeated identical observations are idempotent; later raw API metadata does not overwrite the earlier version's snapshot. Program versions retain detail text and document extraction evidence. This does not archive original document binaries or guarantee trust resolution between conflicting publishers.

Eligibility 2.0.1 records the evaluation date and validates requirement values against their field/operator before evaluation. Korean province aliases normalize common Korean/English spellings. Invalid types and non-finite numbers produce extraction schema failures, not hard eligibility rejection. Alias matching does not interpret district-level restrictions or complex geographic exceptions.

`radar.parallel` reads a current catalog/profile snapshot and compares it with V1's complete pre-send-filter report. It retains ambiguity, failure context and collection-window limitations, and never approves cutover or sends a message. Native PostgreSQL concurrent save/job/cadence/planner/sender tests now pass locally; hosted pooler, API semantics and actual Telegram/network crash behavior remain external validation work.
