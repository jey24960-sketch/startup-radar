PROJECT: StartupRadar 2.0
REPOSITORY: jey24960-sketch/startup-radar
BASELINE: existing main branch

You are rebuilding the existing StartupRadar into StartupRadar 2.0.

This is not a cosmetic refactor.

The existing system is primarily:
fixed URLs -> HTTP crawl -> Claude analysis -> Telegram

The target system must become:
multi-source discovery
-> authoritative source/detail/document acquisition
-> normalized program database
-> structured eligibility requirements
-> deterministic eligibility engine
-> team/stage matching
-> recommendation ranking
-> Telegram alerts + lightweight web dashboard
-> source-health monitoring

The primary objective is NOT "crawl websites successfully."

The primary objective is:

"Discover as many relevant Korean startup support opportunities as reasonably possible, determine whether a GFC startup team can actually apply based on evidence from the original notice, and deliver the right opportunities to the right team at the right time."

==================================================
0. WORKING RULES
==================================================

Before changing code:

1. Audit the current repository and document the actual execution path.
2. Identify obsolete/root duplicate files versus files actually imported/executed.
3. Identify all existing environment variables, workflows, Telegram commands, persistence mechanisms, and deployment dependencies.
4. Preserve the existing production path until an equivalent V2 path works.
5. Do not delete V1 code simply because it appears obsolete until its runtime relevance is confirmed.
6. Keep the repository runnable after each implementation milestone.
7. Add tests for every critical eligibility, deduplication, versioning, and notification behavior.
8. Do not invent API endpoints, API response fields, or credentials.
9. If an external API requires a key that is unavailable, implement the adapter/interface and configuration cleanly and report the missing deployment dependency.
10. Never bypass CAPTCHA, access controls, robots protections, or anti-bot mechanisms.
11. A blocked source is a monitored source failure, not an invitation to bypass the block.
12. Never fabricate support eligibility from incomplete source data.

Use Asia/Seoul as the application timezone for all business dates and notification calculations.

==================================================
1. FIXED PRODUCT DECISIONS
==================================================

These decisions are already approved. Do not reopen them unless implementation reveals a genuine contradiction.

USER SCOPE
- GFC is the initial user.
- Architecture must support multiple teams from the beginning.
- Do not design the database as a single-club/single-profile system.
- Future external startup teams must be supportable without replacing the data model.

RECOMMENDATION MODEL
- Support both:
  A. general browsing by startup stage preset
  B. team-specific recommendations based on an actual team profile

PROGRAM SCOPE

Include:
- 사업화 지원 / grants
- 창업경진대회 / competitions
- incubation
- acceleration
- investment-linked programs
- office / workspace / incubation space
- global expansion
- market-entry programs
- education
- mentoring / consulting

Exclude from the main recommendation feed by default:
- general policy loans
- generic SME financing
- generic R&D programs with no meaningful relevance to early startup teams

The architecture may store excluded categories, but they should not pollute the default GFC feed.

COLLECTION SCOPE
Use a layered discovery architecture:

1. official APIs
2. RSS / Atom
3. HTML list/detail crawling
4. search-based discovery through an explicit provider adapter
5. document/attachment extraction
6. browser rendering only when required

K-Startup and 기업마당 should be treated as first-class backbone sources.

Existing university, accelerator, VC, foundation, and public-sector sources should become supplemental/long-tail source adapters.

ELIGIBILITY POLICY
Eligibility must be evidence-driven.

Public states:
- ELIGIBLE
- NEEDS_INFO
- INELIGIBLE

Internal operational state may additionally include:
- UNVERIFIABLE

Do not let an LLM directly override a deterministic hard eligibility failure.

PROFILE DETAIL
Collect only information materially useful for eligibility.

TELEGRAM / WEB
- Telegram = notification/action channel
- Web = browsing, filtering, evidence, team profile, history, source-health
- Do not attempt to make Telegram the entire database UI.

INFRASTRUCTURE
- GitHub Actions may continue to execute scheduled/manual ingestion jobs.
- Persistent application state must move out of GitHub cache/JSON files.
- Use Supabase/PostgreSQL as the primary persistent database.
- Runtime settings such as team stage must not require editing config.py and committing to Git.

NOTIFICATION POLICY
Support:
- weekly digest
- exceptional high-fit new-program alerts
- deadline reminders

Do not spam users.

==================================================
2. FIVE USER-FACING STARTUP PRESETS
==================================================

The user-facing experience must contain five simple startup states.

PRESET 0
"팀빌딩 전 · 아이디어"

Meaning:
- individual founder or team not formed
- idea exists
- no product required
- no business registration required

This preset MUST work without requiring any detailed founder/team profile.

Default internal assumptions:
team_status = PRE_TEAM
product_stage = IDEA
business_status = PRE_BUSINESS
has_revenue = false

All other attributes remain UNKNOWN unless supplied.

Typical useful programs:
- idea competitions
- pre-startup programs
- team-building programs
- startup camps
- pre-incubation
- mentoring
- founder education
- early validation programs

PRESET 1
"팀 구성 · 아이디어"

Default:
team_status = TEAMED
product_stage = IDEA
business_status = PRE_BUSINESS

PRESET 2
"랜딩 · 프리토타입"

Default:
team_status = TEAMED
product_stage = LANDING
business_status = PRE_BUSINESS

This includes:
- landing page
- fake door
- waitlist
- demand-test prototype
- other pre-MVP validation methods

PRESET 3
"MVP"

Default:
team_status = TEAMED
product_stage = MVP

Business status is independent and must not be inferred unless known.

PRESET 4
"사업자등록 · 법인 보유"

Default:
business_status is one of:
- SOLE_PROPRIETOR
- CORPORATION

Product stage remains independently stored.

IMPORTANT:
These five presets are UX shortcuts, NOT the underlying eligibility data model.

Do not implement them as one linear enum that replaces all other profile fields.

==================================================
3. INTERNAL TEAM PROFILE MODEL
==================================================

At minimum model these dimensions independently.

team_status:
- PRE_TEAM
- FORMING
- TEAMED

product_stage:
- IDEA
- LANDING
- MVP
- REVENUE

business_status:
- PRE_BUSINESS
- SOLE_PROPRIETOR
- CORPORATION

Additional optional eligibility attributes:

- team_size
- founder_age or age_band
- founder/student status
- university affiliation where relevant
- region
- business_registration_date
- business_age_months
- industry tags
- revenue status / coarse revenue band
- investment_received
- investment stage where relevant
- preferred program types
- global expansion interest

Privacy requirement:
Do not collect precise home addresses or birth dates when a coarse region or age/age-band is sufficient.

Implement profile versioning so past eligibility results can be reconstructed against the profile that existed at evaluation time.

==================================================
4. PROGRESSIVE PROFILING
==================================================

Do NOT begin onboarding with a large mandatory profile form.

Initial flow:

1. user selects one of the five presets
2. recommendations become immediately available
3. unknown profile fields remain UNKNOWN
4. when an opportunity depends on unknown information, show exactly which field is missing
5. allow the user to provide that field
6. re-evaluate affected programs

Example:

Program requirement:
- applicant must be <= 39 years old
- pre-business founder
- located in Seoul

Known profile:
business_status = PRE_BUSINESS
age = UNKNOWN
region = UNKNOWN

Result:
NEEDS_INFO

Missing fields:
- founder age
- region

Never convert UNKNOWN into false assumptions.

Stage 0 must remain genuinely usable with no additional personal information.

==================================================
5. INGESTION ARCHITECTURE
==================================================

Create a clean SourceAdapter abstraction.

Conceptual interface:

discover()
fetch_detail()
fetch_documents()
normalize()

Implement/adapt source types:

- KStartupApiAdapter
- BizInfoApiAdapter
- RssAdapter
- HtmlAdapter
- BrowserAdapter
- SearchDiscoveryAdapter

Do not force every source through the same crawling strategy.

SearchDiscoveryAdapter must be provider-agnostic.
Do not scrape consumer search engines directly as a hidden workaround.
If no search provider is configured, disable this adapter cleanly.

BrowserAdapter:
- use only for legitimate JS-rendered public pages
- no CAPTCHA bypass
- no anti-bot evasion logic

Each discovered candidate must preserve provenance:
- source
- source program ID if available
- discovery URL
- official detail URL
- discovered timestamp
- raw metadata

==================================================
6. DOCUMENT PIPELINE
==================================================

Korean support notices frequently place important eligibility rules in attachments.

The V2 pipeline must therefore treat attachments as first-class evidence.

Support, where technically practical:
- HTML
- PDF
- HWP
- HWPX
- DOCX

Architecture must allow additional extractors later.

For each document store:
- original URL
- filename
- detected MIME/type
- content hash
- fetch status
- extraction status
- extracted text
- fetched timestamp

Use safe file limits and MIME validation.

If a document cannot be parsed:
- retain metadata
- mark parsing failure
- do not invent its contents
- allow the program to become UNVERIFIABLE if required evidence is unavailable

==================================================
7. NORMALIZED PROGRAM MODEL
==================================================

Create a canonical normalized Program entity.

Suggested fields include:

id
canonical_key
title
organization
program_types[]
status
application_start_at
application_end_at
deadline_type
official_url
application_url
region_requirements
applicant_summary
support_summary
benefit_summary
amount_min
amount_max
currency
current_version_id
created_at
updated_at

deadline_type should support concepts such as:
- FIXED_DATE
- ROLLING
- UNTIL_BUDGET_EXHAUSTED
- UNKNOWN

Program state must be calculated deterministically from known dates where possible.

Closed programs must not appear as normal current recommendations.

==================================================
8. PROGRAM VERSIONING
==================================================

A support notice may change after initial discovery.

Do not treat:
same title + same URL
as permanently immutable.

Store versions.

Detect meaningful changes such as:
- deadline extension
- target eligibility changes
- benefit changes
- application URL changes
- attached notice replacement
- status changes

Use content hashes plus normalized field comparison.

A changed program may generate an UPDATE event instead of appearing as an entirely new program.

This replaces the weak V1 behavior where URL changes could create duplicates while meaningful changes on the same URL could be missed.

==================================================
9. DEDUPLICATION
==================================================

Prefer authoritative source IDs where available.

Otherwise use a combination of:
- normalized organization
- normalized title
- dates
- source aliases
- URL
- document fingerprint

Implement fuzzy duplicate detection as a candidate mechanism, not reckless automatic merging.

If confidence is ambiguous:
store a possible duplicate relationship for admin review rather than silently merging unrelated programs.

==================================================
10. REQUIREMENT EXTRACTION
==================================================

Eligibility facts may come from:

1. structured official API fields
2. HTML detail pages
3. attachments

Prefer authoritative structured values first.

Represent requirements in a machine-readable structure.

Examples of requirement keys:

business_status
business_age_months
founder_age
region
student_status
team_size
product_stage
revenue
investment_received
industry
applicant_type
registration_date
prior_support_restrictions

Operators should support concepts such as:

EQ
NEQ
IN
NOT_IN
GTE
LTE
RANGE
EXISTS

Every extracted requirement should preserve evidence:

- source/document ID
- location/section where possible
- evidence text
- extraction method
- confidence

An LLM may assist in converting unstructured Korean notice text into this strict requirement schema.

However:

LLM output is not itself the final eligibility decision.

The requirement extraction step must use schema validation.

If the LLM cannot identify reliable evidence:
mark the requirement uncertain.

Never let the model invent a missing rule.

==================================================
11. ELIGIBILITY ENGINE
==================================================

Implement deterministic evaluation of structured program requirements against structured team profiles.

Output:

status:
ELIGIBLE
NEEDS_INFO
INELIGIBLE
UNVERIFIABLE

and:

matched_requirements[]
failed_requirements[]
missing_profile_fields[]
unverifiable_requirements[]
evidence[]

Rules:

INELIGIBLE:
at least one confirmed mandatory requirement fails.

NEEDS_INFO:
no mandatory requirement is known to fail, but one or more required profile attributes are unknown.

ELIGIBLE:
all known mandatory requirements are satisfied and required attributes are available.

UNVERIFIABLE:
source evidence is inadequate to determine one or more critical requirements.

User-facing UI may group UNVERIFIABLE under "조건 확인 필요", but internally preserve the distinction.

The eligibility decision must always be explainable.

Example:

지원 가능
- 예비창업자: 충족
- 팀 구성 여부: 충족
- 사업자등록: 없음 — 충족
- 연령 조건: 만 39세 이하 — 충족

or:

추가 확인 필요
- 대표자 연령
- 서울 소재 여부

==================================================
12. RECOMMENDATION ENGINE
==================================================

Eligibility and recommendation quality are different concepts.

First determine eligibility.

Then rank relevant ELIGIBLE and NEEDS_INFO programs.

A recommendation score may consider configurable weights for:

- startup/product stage fit
- applicant/profile match
- preferred support type
- expected benefit
- GFC/global-market relevance
- useful application runway
- source/data completeness

AI may produce:
- concise summary
- why this program matters
- suggested next action
- semantic relevance signal

AI must NOT override a deterministic INELIGIBLE result.

Store:
- recommendation score
- scoring components
- model/provider
- prompt/schema version
- generated explanation

==================================================
13. DATABASE
==================================================

Use Supabase/PostgreSQL.

At minimum design tables/entities equivalent to:

sources
ingestion_runs
source_run_results

programs
program_sources
program_versions
documents
program_requirements

teams
team_profiles
team_profile_versions

eligibility_evaluations
recommendations

program_change_events

telegram_subscriptions
notification_runs
notification_items

Do not blindly use these exact names if the repository architecture suggests a cleaner implementation, but all capabilities must exist.

Use migrations.

Add appropriate:
- unique constraints
- foreign keys
- indexes
- timestamps
- enum/check constraints

Do not keep critical runtime state solely in GitHub Actions cache.

==================================================
14. SOURCE HEALTH / COVERAGE
==================================================

Build operational observability.

For each source/run track:

- last attempted collection
- last successful collection
- discovered count
- fetched count
- parsed count
- failures
- latency
- error reason

Admin should be able to distinguish:

"no relevant programs"

from:

"source collection failed"

IMPORTANT TERMINOLOGY:

Do NOT claim an arbitrary percentage represents "coverage of every Korean startup support program."

The total denominator is unknowable.

Use terminology such as:

- tracked source health
- monitored-source success rate
- source coverage

Example:

Tracked sources: 42
Successful: 39
Partial: 2
Failed: 1
Tracked-source success rate: 92.9%

This is not equivalent to 92.9% of all startup programs in Korea.

==================================================
15. TELEGRAM V2
==================================================

Preserve Telegram, but redesign its role.

Weekly digest example structure:

StartupRadar Weekly

팀: [team name]
현재 상태: MVP / 사업자등록 전

이번 주:
- 신규 지원 가능 5
- 추가 조건 확인 3
- 마감 임박 2

Top recommendations:

[program]
주관기관
마감 D-12
지원/혜택
적합도
지원 가능 여부
추천 이유
확인된 핵심 조건
원문 보기

Separate:
- ELIGIBLE
- NEEDS_INFO

Never present NEEDS_INFO as confirmed eligible.

HIGH-FIT NEW ALERT

Only send exceptional immediate alerts.

Default policy should be configurable.

Recommended initial criteria:
- newly discovered or materially updated
- eligibility = ELIGIBLE
- recommendation score >= configured high threshold
- enough time remains to reasonably apply
- not previously alerted for the same material version

DEADLINE REMINDERS

Support configurable reminders such as:
- D-7
- D-3

Prevent duplicate reminders.

==================================================
16. TELEGRAM COMMANDS
==================================================

Existing Telegram commands should be audited.

V2 principles:

/run
- trigger a real ingestion workflow

/status
- return actual latest job/source state
- never return a hard-coded "everything is normal" message

/stage
- update profile data in persistent storage
- do NOT edit config.py and push a Git commit

/stop
- if retained, update runtime scheduling configuration/state
- do not edit repository configuration as the primary control plane

Consider useful admin commands such as:
/sources
/health
/team
/digest

Do not add unnecessary commands simply for feature count.

Protect webhook authenticity and administrator authorization.

Implement Telegram update idempotency.

==================================================
17. WEB DASHBOARD
==================================================

Build a lightweight but usable web experience.

Required member functions:

A. stage/preset selector
B. team profile
C. team recommendations
D. all-program browser
E. filters
F. program detail
G. evidence display
H. support eligibility explanation
I. past/updated notices

Required admin functions:

A. source health
B. ingestion run history
C. failed sources
D. parsing failures
E. possible duplicates
F. manually trigger/retry ingestion where appropriate

Program detail should clearly separate:

FACT
information extracted from source

ELIGIBILITY
result of rule engine

RECOMMENDATION
system interpretation

This distinction is mandatory.

==================================================
18. AUTHORIZATION / PRIVACY
==================================================

GFC is initially private/internal.

Use an architecture that supports authenticated users and team membership.

If Supabase Auth is used, prefer an invite/membership-oriented implementation suitable for GFC now and extensible later.

A user must not automatically gain access to other teams' non-public profile information.

Use Row Level Security where appropriate.

Do not expose:
- private team profile attributes
- Telegram IDs
- internal operational metadata
to unauthenticated public users.

Do not store unnecessary sensitive personal data.

==================================================
19. GITHUB ACTIONS
==================================================

GitHub Actions can remain responsible for scheduled ingestion.

Separate concepts:

COLLECTION FREQUENCY
and
DELIVERY FREQUENCY.

High-fit immediate alerts require more frequent collection than one weekly execution.

Implement schedule configuration cleanly.

A reasonable default architecture is:
- daily ingestion
- weekly digest
- separate deadline reminder logic

Do not deeply hard-code these business schedules into multiple files.

Make cadence configurable.

Add concurrency control so manual and scheduled jobs cannot corrupt state or double-send notifications.

A failed critical ingestion/analysis step must generate a failing workflow status where appropriate.

==================================================
20. AI FAILURE HANDLING
==================================================

Never represent:

AI API failure
JSON/schema failure
timeout
rate limit
document parsing failure

as:

"0 new programs"

Return explicit typed failures.

An ingestion run may be:
SUCCESS
PARTIAL_SUCCESS
FAILED

A source may independently be:
SUCCESS
PARTIAL
FAILED

The system must remain capable of delivering valid programs from successful sources when one source fails.

==================================================
21. RAW DATA / TRACEABILITY
==================================================

For a recommendation, an administrator should be able to reconstruct:

- where the program was discovered
- what source version was used
- which documents were parsed
- which requirements were extracted
- what profile version was evaluated
- why the eligibility engine decided its status
- why it was ranked
- whether/when it was notified

Preserve sufficient raw/normalized evidence for this without needlessly storing huge duplicated payloads.

==================================================
22. V1 MIGRATION
==================================================

Do not attempt a dangerous one-shot rewrite.

Implement migration in stages.

MILESTONE 1
Current-system audit + reliability safety fixes

At minimum address critical V1 issues necessary to safely coexist during migration:
- analysis error vs empty result
- actual sent items vs marked-as-sent mismatch
- workflow failure signaling
- concurrency where practical
- webhook authenticity/idempotency where applicable

MILESTONE 2
Supabase persistent data layer

MILESTONE 3
Program/source/document canonical schema

MILESTONE 4
official API adapters
- K-Startup
- 기업마당

MILESTONE 5
long-tail adapters and attachment extraction

MILESTONE 6
requirements + eligibility engine

MILESTONE 7
team profiles + five presets + progressive profiling

MILESTONE 8
recommendation and Telegram V2

MILESTONE 9
web dashboard + source health

MILESTONE 10
parallel-run validation and V1 cutover

During parallel run:
compare V1 vs V2 discovered programs and investigate:
- V1-only items
- V2-only items
- duplicate behavior
- eligibility disagreements
- failed-source behavior

Only retire V1 after V2 demonstrates acceptable reliability.

==================================================
23. TEST REQUIREMENTS
==================================================

Create proper automated tests.

At minimum cover:

PRESET / PROFILE
- Stage 0 works with no optional profile data
- unknown fields remain unknown
- preset does not overwrite explicitly entered profile data

ELIGIBILITY
- all conditions satisfied -> ELIGIBLE
- one hard failure -> INELIGIBLE
- required unknown attribute -> NEEDS_INFO
- unavailable evidence -> UNVERIFIABLE
- multiple requirements
- age ranges
- region restrictions
- business age
- pre-business-only programs
- registered-company-only programs

DATES
- open
- upcoming
- closed
- D-7/D-3
- rolling deadlines
- Asia/Seoul boundaries

DEDUP
- same program from multiple sources
- changed URL
- deadline extension
- title normalization
- ambiguous fuzzy match does not incorrectly merge

NOTIFICATIONS
- only actually delivered items recorded as delivered
- partial Telegram failure
- duplicate alert prevention
- reminder idempotency
- material update can notify once

INGESTION
- one source fails, others continue
- API empty response vs API failure
- document parse failure
- malformed AI response
- schema validation failure

SECURITY
- unauthorized Telegram update
- duplicate Telegram update
- team isolation / RLS where applicable

==================================================
24. ACCEPTANCE CRITERIA
==================================================

StartupRadar 2.0 is not complete merely because the code builds.

The following must be demonstrated.

1. A new user can select "팀빌딩 전 · 아이디어" without entering detailed information and immediately browse relevant opportunities.

2. A team can create/update a structured profile.

3. The same program can produce different eligibility results for two different teams.

4. A requirement dependent on unknown team data produces NEEDS_INFO rather than a guessed yes/no.

5. A program that explicitly requires an existing business is INELIGIBLE for a PRE_BUSINESS profile.

6. The user can see evidence supporting important eligibility conditions.

7. A PDF/HWP/HWPX extraction failure is visible and does not silently become false eligibility information.

8. Programs discovered from multiple sources can be deduplicated while retaining provenance.

9. Material program updates create versions.

10. Closed programs are deterministically filtered.

11. K-Startup and 기업마당 adapters are implemented or, if blocked only by credentials, fully wired and documented with the exact missing configuration.

12. At least one non-API source adapter demonstrates the long-tail architecture.

13. Telegram weekly digest uses real team eligibility results.

14. /status reflects real application/ingestion state.

15. Runtime stage/team changes no longer require Git commits.

16. Admin can see tracked-source success/failure.

17. Source failure never masquerades as "there were simply no programs."

18. GitHub Actions concurrency and notification idempotency prevent obvious duplicate processing.

19. The system stores enough trace information to explain a recommendation after the fact.

20. Existing V1 behavior is not removed until the replacement path is validated.

==================================================
25. DOCUMENTATION / FINAL HANDOFF
==================================================

Update README and architecture documentation.

Provide:

- architecture diagram
- environment variables
- Supabase setup
- migrations
- source adapter guide
- how to add a new source
- requirement schema
- eligibility semantics
- recommendation scoring
- Telegram deployment
- GitHub Actions schedule
- web deployment
- failure/retry behavior
- privacy/security notes
- V1 -> V2 migration notes

Create an explicit "Adding a Source" guide so a future contributor does not need to modify core ingestion logic for every new organization.

At final handoff report:

FILES CHANGED
DATABASE MIGRATIONS
NEW ENVIRONMENT VARIABLES
NEW WORKFLOWS
TEST RESULTS
BUILD RESULTS
EXTERNAL SETUP STILL REQUIRED
KNOWN LIMITATIONS
CUTOVER STATUS

==================================================
26. NON-GOALS
==================================================

Do not:

- promise literal 100% coverage of every Korean startup program
- scrape every possible site indiscriminately
- bypass anti-bot protections
- allow AI to fabricate eligibility
- require full personal information before showing value
- treat startup maturity as only one database enum
- retain JSON files as the primary database
- use Git commits as user profile storage
- send every discovered program to every GFC team
- optimize visual design before ingestion/eligibility correctness
- silently swallow external API, crawler, document, AI, or Telegram failures

==================================================
27. PRODUCT PRINCIPLE
==================================================

The primary success metric is not:
"How many pages did StartupRadar scrape?"

The system should optimize for:

"How reliably can a GFC founder discover an opportunity that they can actually apply to, understand why it is relevant, verify the eligibility evidence, and act before the deadline?"

Implement toward that objective.