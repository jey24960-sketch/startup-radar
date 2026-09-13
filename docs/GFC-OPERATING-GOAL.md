# StartupRadar 2.0 — Vertical Slice First / GFC 통합 운영 완성 Goal

PROJECT
StartupRadar 2.0

PRIMARY REPOSITORIES

- jey24960-sketch/startup-radar
- jey24960-sketch/GFC-startup.com

PRIMARY SUPABASE

- Existing GFC production Supabase project
- Project ref: etvffzxqdgblvkfdikwl

APPLICATION TIMEZONE

- Asia/Seoul

\==================================================
0\. THIS GOAL REPLACES THE PREVIOUS GOAL
========================================

This Goal replaces the previous StartupRadar 2.0 Goal as the single current
source of truth.

DO NOT restart the project.
DO NOT discard completed work.
DO NOT rebuild already-implemented functionality from scratch.

The current implementation checkpoint is the baseline.

The most important change in this Goal is PRIORITY.

The project has already spent substantial implementation time on architecture,
database, security, UI, tests and operational foundations.

The immediate objective is now:

PROVE THE FIRST REAL END-TO-END VERTICAL SLICE.

Until that vertical slice succeeds, scope expansion is prohibited.

The first real success is:

REAL K-Startup or BizInfo opportunity
→ real external API response
→ StartupRadar ingestion
→ normalization
→ Supabase persistence
→ eligibility evaluation
→ recommendation
→ actual authenticated GFC member
→ gfc-startup.com /notice
→ real opportunity visible
→ detail page shows official source/evidence

This must happen before further platform expansion.

\==================================================

1. CURRENT IMPLEMENTATION BASELINE — PRESERVE
   \==================================================

The following capabilities are already substantially implemented and must be
preserved.

STARTUPRADAR BACKEND

- multi-source ingestion architecture
- official API / RSS / HTML adapters
- attachment/document processing foundation
- normalized program model
- provenance
- program versioning
- deduplication
- requirement extraction
- deterministic eligibility engine
- recommendation scoring
- notification history/outbox
- source health
- team profile/version model
- five startup presets
- progressive profiling
- evidence model
- typed failures
- PostgreSQL persistence
- analysis/result caching
- V1 reliability fixes

GFC INTEGRATION

- shared existing Supabase project
- separate startup\_radar schema
- manual GFC notice model
- existing GFC Auth integration
- verified-member Radar access
- RLS
- /notice
- manual notice detail/admin flows
- Radar program/detail flows
- team selector
- Radar settings
- admin health UI where implemented

TEST INFRASTRUCTURE

- Python tests
- Worker tests
- PostgreSQL/PGlite migration tests
- GFC Node tests
- Playwright tests
- production schema regression checks

Do not increase test count merely for its own sake.

Existing tests must remain green, but real end-to-end evidence now has higher
priority than additional synthetic coverage.

\==================================================
2\. IMMEDIATE PRIORITY — HARD GATE
==================================

STOP expanding the system until the following vertical slice passes.

VERTICAL SLICE ACCEPTANCE TEST

At least one REAL CURRENT opportunity from K-Startup or 기업마당 must:

1. be fetched using the real issued API credential,
2. be parsed successfully,
3. be normalized into the StartupRadar program model,
4. be persisted in the real shared Supabase project,
5. retain official source/provenance,
6. have eligibility requirements extracted where possible,
7. be evaluated against a real controlled Radar team/profile,
8. receive an eligibility result,
9. receive a recommendation result,
10. appear to an authenticated verified GFC member in the GFC /notice UI,
11. open in the Radar program detail page,
12. show official source URL and available evidence,
13. remain inaccessible to an anonymous or authenticated non-member user.

This must use NON-FIXTURE data.

A successful Python test, mock response, seeded program, Playwright fixture or
manual DB insert does NOT satisfy this gate.

If the flow fails at any step:

FOCUS ONLY ON THAT BLOCKING STEP UNTIL IT PASSES.

Do not move sideways into unrelated enhancements.

\==================================================
3\. WORK THAT IS PAUSED UNTIL THE HARD GATE PASSES
==================================================

Until Section 2 succeeds, do NOT spend time on:

- adding more long-tail sources
- Telegram feature expansion
- V1/V2 parallel comparison
- production cutover planning
- advanced admin dashboard work
- advanced analytics
- broad legacy security cleanup
- comprehensive documentation expansion
- additional UI polish
- advanced global pagination
- additional caching sophistication
- new source-provider abstractions unless required by the vertical slice
- unrelated refactoring
- raising test count without a blocker-driven reason
- premature hosting architecture work
- full Python API redesign

Only modify these areas if they directly block the real vertical slice.

\==================================================
4\. AVAILABLE RUNTIME CREDENTIALS
=================================

The user has prepared the following worker credentials/configuration.

Expected in the local worker environment:

DATABASE\_URL
ANTHROPIC\_API\_KEY
KSTARTUP\_API\_KEY
BIZINFO\_API\_KEY

Do not ask the user to paste secret values into chat.

First verify only:

- variable exists,
- variable is non-empty,
- the target service accepts it.

Never print complete secret values into logs.

If one credential fails:

report:

- variable name,
- service,
- safe error summary,
- exact configuration location,

without exposing the secret.

Do not block use of K-Startup because BizInfo fails, or vice versa.

\==================================================
5\. FIRST REAL DATA SOURCE PRIORITY
===================================

For the first vertical slice, prioritize official structured APIs.

FIRST:
K-Startup

Relevant service:
창업진흥원\_K-Startup(사업소개,사업공고,콘텐츠 등)\_조회서비스

Priority endpoint:

- 지원사업 공고 정보
- getAnnouncementInformation01

Useful secondary endpoint:

- 통합공고 지원사업 정보
- getBusinessInformation01

SECOND:
기업마당 지원사업정보 API

Do NOT begin with difficult university/JS/blocked sites.

The objective is not source breadth yet.

The objective is proving:

official source
→ real database
→ real eligibility
→ real GFC UI.

\==================================================
6\. FIRST VERTICAL SLICE EXECUTION ORDER
========================================

Execute in this exact order unless a technical dependency requires otherwise.

STEP 1 — ENVIRONMENT

Verify:

DATABASE\_URL
ANTHROPIC\_API\_KEY
KSTARTUP\_API\_KEY
BIZINFO\_API\_KEY

Do not expose their values.

STEP 2 — DATABASE CONNECTION

Prove StartupRadar Python can connect to:

Supabase project:
etvffzxqdgblvkfdikwl

Verify read/write access only to intended StartupRadar structures.

Do not alter unrelated GFC production objects.

STEP 3 — K-STARTUP REAL FETCH

Perform a real K-Startup API request.

Record:

- HTTP result
- response count
- request endpoint
- safe request metadata
- no secret values

STEP 4 — INGEST SMALL SAMPLE

Do NOT immediately ingest the entire available history.

Take a bounded current sample.

Prefer:

- currently recruiting
- recently published
- relevant startup support programs

Run the real normalization pipeline.

STEP 5 — PERSIST

Write the real program(s) to Supabase using the normal V2 code path.

Do not manually insert rows merely to make the UI work.

STEP 6 — REQUIREMENTS / AI

Use authoritative structured fields first.

Use Anthropic only where unstructured content actually requires extraction.

Do not invoke AI unnecessarily.

STEP 7 — ELIGIBILITY

Use an existing controlled validation team or create one explicitly for the
test.

Do not alter unrelated real member teams.

Generate:

ELIGIBLE
NEEDS\_INFO
INELIGIBLE
or
UNVERIFIABLE

through the real eligibility engine.

STEP 8 — RECOMMENDATION

Generate and persist the real recommendation using the normal code path.

STEP 9 — GFC WEB

Make the real program appear in the actual member Radar feed used by /notice.

The program must not be fixture data.

STEP 10 — DETAIL

Open the real program detail.

Verify:

FACT
ELIGIBILITY
RECOMMENDATION
official source
evidence
documents where available

STEP 11 — ACCESS CONTROL

Verify:

anonymous
→ cannot retrieve Radar data

authenticated external/non-member
→ cannot retrieve Radar data

verified member
→ can retrieve allowed Radar data

STEP 12 — REPORT

Report the first real vertical slice as:

PASS
or
BLOCKED AT STEP N.

Do not describe it as complete unless all required steps pass.

\==================================================
7\. FINAL SYSTEM ARCHITECTURE
=============================

Target architecture:

GitHub Actions
↓
StartupRadar Python batch worker
↓
source discovery / documents / normalization
↓
requirements / eligibility / recommendations
↓
Supabase
↑
gfc-startup.com

Telegram
← notification pipeline

RESPONSIBILITIES

StartupRadar Python:

- scheduled ingestion
- external source communication
- document processing
- normalization
- deduplication
- versioning
- requirement extraction
- eligibility batch evaluation
- recommendation calculation
- notification generation
- source health

Supabase:

- persistence
- Auth
- RLS
- manual GFC notices
- StartupRadar programs
- documents
- requirements
- teams/profiles
- eligibility
- recommendations
- notification state
- operational state

gfc-startup.com:

- primary user-facing interface
- /notice
- manual notices
- Radar opportunity browsing
- program detail
- team/profile/settings
- eligibility evidence
- admin notice management
- limited operational status

Telegram:

- secondary notification channel

\==================================================
8\. PYTHON API — DO NOT MAKE THIS A PRECONDITION
================================================

A standalone hosted Python HTTP API is NOT a prerequisite for Section 2.

Do NOT stop the vertical slice merely because VITE\_RADAR\_API\_URL has no
production URL.

For the first real vertical slice:

use the minimum-change safe path that allows the real program to reach the
actual GFC UI.

Possible mechanisms:

A. direct Supabase access under RLS
B. safe view/RPC
C. existing locally/preview-connected Python API where appropriate

Do NOT perform a full API architecture refactor before the vertical slice.

Do NOT provision paid permanent hosting merely to satisfy an old assumption.

AFTER the vertical slice passes, audit each current API endpoint and classify:

DIRECT SUPABASE
SAFE VIEW/RPC
ASYNC JOB
PYTHON API REQUIRED

Only then decide whether persistent Python hosting is necessary.

Preserve reusable Python service/domain logic regardless of HTTP deployment.

\==================================================
9\. SUPABASE DECISION
=====================

Do NOT create a new Supabase project.

Use:

jey24960-sketch's Project

Project ref:

etvffzxqdgblvkfdikwl

StartupRadar-specific data remains under:

startup\_radar

Existing GFC production objects must remain protected.

Do not destructively modify:

public.profiles
public.projects
public.teams
public.problems
auction objects
existing Auth structures

Manual GFC notices and automatic Radar opportunities remain separate data
domains.

\==================================================
10\. GFC /NOTICE MODEL
======================

Primary information hub:

/notice

Two logical content types:

A. MANUAL GFC NOTICES

- authored by GFC operators
- PUBLIC or MEMBERS\_ONLY

B. STARTUPRADAR OPPORTUNITIES

- automatically sourced
- verified-member only
- team/preset dependent

Do not duplicate Radar programs into the manual notice table.

Member combined feed may visually merge both sources.

\==================================================
11\. AUTHORIZATION
==================

AUTHENTICATED != VERIFIED GFC MEMBER.

Anonymous:

- PUBLIC manual notices only

Authenticated external/non-member:

- PUBLIC manual notices only

Verified GFC member:

- PUBLIC notices
- MEMBERS\_ONLY notices
- permitted StartupRadar data

GFC admin/operator:

- member capabilities
- manual notice administration
- authorized Radar operational views

Security must be enforced by database/API authorization.

Frontend hiding alone is insufficient.

Team-private data remains team-isolated.

Service-role secrets must never reach browser code.

\==================================================
12\. STARTUP STAGE MODEL
========================

Preserve the five UX presets.

0. 팀빌딩 전 · 아이디어
1. 팀 구성 · 아이디어
2. 랜딩 · 프리토타입
3. MVP
4. 사업자등록 · 법인 보유

These are presets, not the real internal state model.

Keep independent:

team\_status
product\_stage
business\_status

Stage 0 must work without a long profile form.

Known defaults:

team\_status = PRE\_TEAM
product\_stage = IDEA
business\_status = PRE\_BUSINESS
has\_revenue = false

Everything else remains UNKNOWN until provided.

UNKNOWN != false.

\==================================================
13\. PROGRESSIVE PROFILING
==========================

Preferred flow:

select preset
→ see useful opportunities
→ program needs missing information
→ NEEDS\_INFO
→ show exact missing fields
→ optional user input
→ re-evaluate

Do not force complete personal information before showing value.

\==================================================
14\. ELIGIBILITY
================

Internal states:

ELIGIBLE
NEEDS\_INFO
INELIGIBLE
UNVERIFIABLE

INELIGIBLE:
confirmed mandatory requirement fails.

NEEDS\_INFO:
required team/user attribute is unknown.

ELIGIBLE:
required conditions are satisfied.

UNVERIFIABLE:
program evidence is insufficient.

LLM cannot override a deterministic hard failure.

Every meaningful decision should retain evidence where practical.

\==================================================
15\. RECOMMENDATION
===================

Eligibility and recommendation remain separate.

First:

Can this team apply?

Then:

How useful is this opportunity?

Possible factors:

- stage fit
- applicant fit
- preferred support type
- benefit
- global relevance
- deadline runway
- source completeness

AI may help with summary/explanation.

Do not regenerate recommendation text on every page request.

Cache/store usable results.

\==================================================
16\. DOCUMENT EVIDENCE
======================

Documents remain first-class evidence.

Support where practical:

HTML
PDF
HWP
HWPX
DOCX

For the FIRST vertical slice, however:

do not block successful real program display merely because the selected
program has no attachment or a non-critical attachment cannot be parsed.

If a critical document cannot be parsed:

mark it honestly.

Do not invent its contents.

After the vertical slice passes, expand attachment validation.

\==================================================
17\. AUTOMATION AFTER VERTICAL SLICE
====================================

Only after Section 2 passes, move to actual automation.

Target conceptual schedule:

daily ingestion
→ detect new/changed opportunities
→ process
→ evaluate teams
→ update recommendations

weekly digest
→ useful team opportunities

deadline checks
→ D-7 / D-3

Keep schedule configuration centralized.

Keep V2 recurring schedule disabled until one manual real-data run is proven.

\==================================================
18\. COST CONTROL
=================

Avoid unnecessary AI cost.

Same document/content hash:
→ reuse prior successful extraction

New/materially changed:
→ analyze

Eligibility:
→ deterministic code where possible

Page view:
→ no unnecessary AI call

Do not ingest huge historical datasets merely to prove the system works.

\==================================================
19\. SOURCE EXPANSION — AFTER HARD GATE
=======================================

After the vertical slice passes:

Priority:

1. K-Startup robust operation
2. 기업마당 robust operation
3. RSS/Atom
4. HTML sources
5. public JS-rendered sources where legitimate
6. search discovery if configured
7. long-tail universities / public institutions / accelerators / foundations

Do not bypass CAPTCHA or anti-bot protections.

A blocked source is a tracked failure.

\==================================================
20\. LIVE ACCOUNT VALIDATION — AFTER REAL PROGRAM APPEARS
=========================================================

After actual opportunity display succeeds, validate deployed roles:

anonymous
authenticated external
verified member
admin

Verify:

- login
- member recognition
- manual notice visibility
- Radar access
- team access
- profile update
- team switch
- evidence
- admin notice flow
- mobile

Use controlled accounts.

Do not alter unrelated users.

\==================================================
21\. TELEGRAM — AFTER REAL WEB FLOW
===================================

Telegram is notification-only.

After real web flow is proven, validate:

- weekly-style digest
- high-fit opportunity
- D-7
- D-3
- duplicate prevention
- preference enforcement
- partial failure behavior

Use only approved test recipients.

Do not expand Telegram before the real /notice opportunity flow works.

\==================================================
22\. V1/V2 PARALLEL COMPARISON — LATE PHASE
===========================================

Do NOT spend time on V1/V2 comparison before the V2 real vertical slice and
basic automation work.

Then compare over the same window:

- discovered programs
- V1-only
- V2-only
- duplicates
- missed opportunities
- deadlines
- eligibility disagreements
- failed sources
- notification behavior

Investigate meaningful disagreements.

\==================================================
23\. TESTING POLICY
===================

Keep existing test suites green.

Add tests only when:

- fixing an actual bug,
- implementing a required behavior,
- preventing a discovered regression,
- changing architecture.

Do not use test count as a project success metric.

The current most important test is:

REAL SOURCE
→ REAL DB
→ REAL ELIGIBILITY
→ REAL GFC UI.

\==================================================
24\. PRODUCTION SAFETY
======================

The shared Supabase project is production infrastructure.

Before new DDL:

- inspect affected objects
- check destructive changes
- check grants
- check RLS
- check auth impact
- check GFC regression

Prefer additive migrations.

Do not casually run blanket db push/migration repair.

Do not perform broad unrelated GFC refactors.

\==================================================
25\. CUTOVER RULE
=================

V1 remains available.

V2 production recurring automation remains disabled until:

- real source ingestion works
- real /notice program display works
- RLS live validation passes
- source failures are visible
- notification behavior has been tested
- V1/V2 comparison has been reviewed

Do not perform irreversible cutover without explicit approval.

\==================================================
26\. PHASES AFTER THE FIRST VERTICAL SLICE
==========================================

Once Section 2 passes, continue in this order.

PHASE 2
K-Startup + BizInfo robustness

- broader current dataset
- attachments
- update/version behavior
- failures

PHASE 3
real-role browser validation

- external/member/admin
- mobile
- profile updates

PHASE 4
scheduled GitHub Actions automation

- one controlled scheduled ingestion
- concurrency
- failure status

PHASE 5
Telegram notification validation

PHASE 6
source expansion

PHASE 7
V1/V2 parallel comparison

PHASE 8
cutover proposal

Do not reorder these into another large parallel expansion unless an actual
dependency requires it.

\==================================================
27\. REPORTING DURING THE HARD-GATE PHASE
=========================================

Until the first vertical slice succeeds, keep reports short.

Use:

CURRENT BLOCKER

LAST SUCCESSFUL STEP

REAL DATA STATUS

NEXT ACTION

USER ACTION REQUIRED

- only if genuinely required

Do NOT generate another comprehensive architecture report every few minutes.

Do NOT repeatedly report that the same secret/config is missing once the user
has supplied/configured it.

Do NOT remain in passive waiting if another independent part of the vertical
slice can be progressed.

\==================================================
28\. FIRST VERTICAL SLICE COMPLETION REPORT
===========================================

When Section 2 succeeds, report:

REAL SOURCE

- source
- endpoint
- number of real records fetched

REAL PROGRAM

- title
- organization
- deadline
- official URL
- real, not fixture

DATABASE

- program ID
- version persisted
- requirement/evidence status

TEAM

- validation team
- preset/profile state

ELIGIBILITY

- result
- key reasons

RECOMMENDATION

- score/status
- short reason

GFC WEB

- actual route
- member visibility confirmed

ACCESS CONTROL

- anonymous denied
- non-member denied
- member allowed

SCREENSHOT OR OTHER EVIDENCE

- if available

BLOCKERS REMAINING

NEXT PHASE

Do not include secret values.

\==================================================
29\. DEFINITION OF DONE
=======================

StartupRadar 2.0 is DONE only when:

a GFC member can:

- visit gfc-startup.com
- read GFC notices
- see actual StartupRadar opportunities
- select/manage a team
- use Stage 0 without full profiling
- understand eligibility
- inspect evidence
- see recommendations

while an external user:

- can read PUBLIC notices
- cannot retrieve member-only Radar data

and the system automatically:

- collects real opportunities
- processes authoritative information/documents
- versions changes
- evaluates teams
- updates recommendations
- tracks failures
- sends configured notifications

and operators can:

- manage manual notices
- inspect ingestion/source health

and:

- real external sources were validated
- real Supabase was validated
- actual roles were validated
- deployed GFC UI was validated
- approved notifications were validated
- V1/V2 comparison was reviewed
- existing GFC production service remains intact.

\==================================================
30\. CORE PRINCIPLE
===================

The immediate question is:

"Can we get one real support opportunity all the way from an official source
to a real GFC member's /notice screen, with real eligibility and evidence?"

Until the answer is YES, do not optimize secondary systems.

After the answer is YES, scale the pipeline safely.

Optimize ultimately for:

"Can a GFC founder reliably find an opportunity they can actually apply to,
understand why, verify the evidence, and act before the deadline?"

Not:

"How many hours did the Goal run?"

Not:

"How many tests did we create?"

Not:

"How much infrastructure did we build?"

Not:

"How many sources did we theoretically support?"

Real usable data flow comes first.