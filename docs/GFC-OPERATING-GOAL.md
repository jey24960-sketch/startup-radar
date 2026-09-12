# StartupRadar 2.0 — GFC 통합 운영 완성 Goal

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

DO NOT rebuild already-implemented functionality merely because this Goal is
newly written.

The current implementation checkpoint is the baseline.

Preserve and continue from all already completed work unless a specific item
below explicitly changes the architecture.

The purpose of this Goal is:

1. preserve the completed StartupRadar V2 backend/database/security work,
2. preserve the completed GFC /notice integration work,
3. remove obsolete deployment assumptions,
4. connect the system to real operating data and accounts,
5. validate actual end-to-end operation,
6. compare V1 and V2 in parallel,
7. prepare a safe production cutover.

\==================================================

1. CURRENT IMPLEMENTATION BASELINE — DO NOT REDO
   \==================================================

The following work is already considered implemented and should be preserved,
audited, fixed if necessary, but not independently rebuilt from scratch.

STARTUPRADAR BACKEND

- multi-source ingestion architecture
- official API / RSS / HTML source adapters
- attachment/document processing foundation
- normalized program model
- program provenance
- program versioning
- deduplication
- requirement extraction
- deterministic eligibility engine
- recommendation scoring
- notification history/outbox
- source health and ingestion state
- team profile/version model
- five startup presets
- progressive profiling model
- eligibility evidence
- failure typing
- V1 reliability fixes
- PostgreSQL persistence
- caching of unchanged analysis where already implemented

GFC INTEGRATION

- shared existing Supabase project
- separate startup\_radar schema
- public manual notice model
- GFC membership-based Radar access
- RLS policies
- /notice frontend
- manual notice detail/admin flows
- Radar result/detail flows
- team selector
- Radar settings UI
- admin health UI where implemented
- existing GFC authentication integration

TESTING ALREADY EXISTS FOR

- Python backend
- Worker
- PostgreSQL migrations/RLS
- GFC Node/PGlite
- browser/Playwright
- production-schema regression

Existing tests must continue to pass.

\==================================================
2\. FINAL PRODUCT DEFINITION
============================

StartupRadar is an internal GFC startup-support opportunity intelligence
system.

Its primary objective is:

"Help a GFC founder discover startup support opportunities they can actually
apply to, understand why they qualify, verify the evidence, and act before
the deadline."

It is NOT merely a website crawler.

It is NOT a standalone SaaS product for GFC members.

It is NOT a separate member-facing Python web service.

The final operating experience should feel like:

"GFC 웹사이트 안에서 운영진 공지와 나에게 필요한 창업지원사업을
한 곳에서 확인한다."

\==================================================
3\. FINAL SYSTEM ARCHITECTURE
=============================

The intended architecture is:

SOURCE COLLECTION
↓
StartupRadar Python batch worker
↓
normalization / documents / requirements / eligibility / recommendations
↓
Supabase
↓
gfc-startup.com
↓
GFC members

Telegram remains a notification channel.

Conceptually:

GitHub Actions
↓
StartupRadar Python
↓
Supabase
↑
gfc-startup.com

Telegram
← notification pipeline

Responsibilities:

A. StartupRadar Python

- source discovery
- API/RSS/HTML collection
- document retrieval
- PDF/HWP/HWPX/etc extraction
- normalization
- deduplication
- versioning
- requirement extraction
- deterministic eligibility evaluation
- recommendation calculation
- notification generation
- source-health tracking

B. Supabase

- persistent database
- authentication
- authorization / RLS
- GFC manual notices
- programs
- documents
- requirements
- team profiles
- eligibility
- recommendations
- notification state
- operational state

C. gfc-startup.com

- user-facing UI
- manual notice consumption
- StartupRadar opportunity consumption
- team selector
- profile/settings management
- evidence display
- operator notice management
- appropriate admin monitoring

D. Telegram

- weekly digest
- exceptional high-fit opportunities
- D-7 / D-3 reminders
- limited operational alerts

\==================================================
4\. IMPORTANT ARCHITECTURE CHANGE — PYTHON API
==============================================

A standalone hosted Python HTTP API is NOT a mandatory architecture component.

There is currently no requirement to create Railway, Render, Fly.io, or any
other always-on Python hosting merely because the current frontend code uses
VITE\_RADAR\_API\_URL.

Do NOT pause the Goal waiting for an existing Python API URL.

Do NOT treat Python API hosting as a blocking prerequisite.

Audit the currently implemented FastAPI/API layer and classify every endpoint
into one of three groups.

GROUP A — DIRECT SUPABASE ACCESS IS APPROPRIATE

Use Supabase JS + authenticated JWT + RLS, safe views, or safe RPC where this
is simpler and secure.

Candidates may include:

- member feed reads
- team list reads
- team profile reads
- program detail reads
- recommendation reads
- notification preference reads
- manual notice reads/writes where already safe

GROUP B — SERVER-SIDE OPERATION IS ACTUALLY REQUIRED

Retain a server-side mechanism only when necessary, for example:

- privileged secret-dependent external API calls
- long-running ingestion
- AI analysis
- attachment processing
- administrative orchestration
- jobs that cannot securely execute in the browser

These should normally run from GitHub Actions / batch workers rather than
become synchronous public HTTP endpoints.

GROUP C — REAL-TIME SERVER ACTION MAY BE JUSTIFIED

If some feature genuinely requires an immediate server-side response,
for example an on-demand eligibility recalculation after a profile change,
first evaluate:

1. deterministic DB-side evaluation
2. async job/outbox
3. GitHub Actions dispatch
4. Supabase Edge Function
5. existing Python API

in that order based on security, complexity, latency and cost.

Do NOT preserve a standalone Python API merely because it already exists.

Do NOT delete the existing API layer blindly either.

Reuse backend/service logic even if the public HTTP layer becomes unnecessary.

If any Python HTTP endpoint remains necessary for production, explicitly report:

- endpoint
- caller
- reason
- why Supabase/RPC/batch cannot replace it
- expected traffic
- authentication
- required secrets
- hosting requirement
- estimated operational cost

before treating hosting as a deployment blocker.

\==================================================
5\. SUPABASE DECISION
=====================

Do NOT create a new Supabase project.

Use:

jey24960-sketch's Project

Project ref:

etvffzxqdgblvkfdikwl

This project is shared with the existing GFC production website.

Therefore protection of the existing GFC application has higher priority than
StartupRadar implementation speed.

\==================================================
6\. DATABASE ISOLATION
======================

StartupRadar-specific data remains isolated under:

startup\_radar

Existing GFC public tables must not be repurposed.

Do not destructively modify:

public.profiles
public.projects
public.teams
public.problems
existing auction objects
existing authentication objects

Manual GFC notices may remain in the established public GFC notice model.

StartupRadar automated programs must NOT be copied into the manual notice
table.

The system should retain:

manual GFC content
and
automated StartupRadar content

as separate data domains even if they appear in one feed.

\==================================================
7\. SHARED AUTHENTICATION
=========================

Use the existing Supabase Auth system used by gfc-startup.com.

Do not create a second StartupRadar login system.

However:

AUTHENTICATED != VERIFIED GFC MEMBER

StartupRadar access requires verified GFC membership.

The existing GFC role/membership model should be reused where safe.

Current intended model:

anonymous
→ PUBLIC GFC notices only

authenticated external/non-member
→ PUBLIC GFC notices only

verified GFC member
→ PUBLIC notices
→ MEMBERS\_ONLY notices
→ StartupRadar member functionality

GFC admin/operator
→ member functionality
→ manual notice administration
→ appropriate Radar administration

Do not use editable user metadata as the authoritative security boundary.

\==================================================
8\. RLS IS THE SECURITY BOUNDARY
================================

Frontend hiding is not authorization.

Anonymous and non-member users must be unable to retrieve StartupRadar private
data through:

- direct Supabase REST
- browser DevTools
- crafted client queries
- RPC calls
- alternate frontend routes

Use RLS and database permissions.

Team-private data must also remain isolated between members.

A verified member does NOT automatically receive access to every team profile.

Service-role credentials must never be sent to browser code.

\==================================================
9\. GFC NOTICE HUB
==================

Primary page:

/notice

This is the GFC information hub.

It contains two content systems.

A. MANUAL GFC NOTICE

Written by GFC operators.

Examples:

- general notices
- session notices
- recruitment
- events
- important operational notices

Visibility:

PUBLIC
MEMBERS\_ONLY

B. STARTUPRADAR OPPORTUNITY

Generated from StartupRadar data.

Only verified GFC members may access the Radar opportunity system.

Do NOT convert automated StartupRadar programs into manual notice rows.

\==================================================
10\. /NOTICE USER EXPERIENCE
============================

Anonymous/external users:

- see public GFC notices
- may see a locked explanation that StartupRadar is a GFC member benefit
- must NOT receive actual Radar titles, counts, program data or private metadata

Verified GFC members:

tabs may include:

[전체]
[GFC 공지]
[StartupRadar]

The combined feed may visually merge the two data sources.

Example:

[공지]
GFC 세션 일정 변경
운영진

[지원사업]
글로벌 창업 지원사업
지원 가능
D-12
적합도 94

But the storage models remain independent.

\==================================================
11\. MANUAL NOTICE ADMINISTRATION
=================================

Authorized GFC admins/operators should be able to:

- create
- edit
- publish
- schedule if supported
- unpublish if supported
- pin
- archive

manual notices.

PUBLIC should remain the default visibility unless a different existing
production convention is already established.

Preserve author/audit information internally.

Avoid unnecessary destructive deletion.

\==================================================
12\. STARTUPRADAR MEMBER SETTINGS
=================================

StartupRadar configuration should be managed from the GFC website.

Do not use Git commits or config.py as the primary user profile control plane.

Users should be able to manage:

- radar team
- active team
- startup preset
- team status
- product stage
- business status
- relevant eligibility attributes
- preferred support types
- notification preferences

\==================================================
13\. FIVE STARTUP PRESETS
=========================

Preserve these five user-facing presets.

0. 팀빌딩 전 · 아이디어
1. 팀 구성 · 아이디어
2. 랜딩 · 프리토타입
3. MVP
4. 사업자등록 · 법인 보유

These are UX presets only.

Underlying dimensions remain independent:

team\_status
product\_stage
business\_status

Do NOT collapse maturity into one irreversible enum.

\==================================================
14\. STAGE 0 REQUIREMENT
========================

Stage 0 must work without requiring detailed personal/team information.

Default known state:

team\_status = PRE\_TEAM
product\_stage = IDEA
business\_status = PRE\_BUSINESS
has\_revenue = false

Other profile fields remain UNKNOWN.

UNKNOWN must never silently become false.

If an opportunity requires an unknown property:

→ NEEDS\_INFO

not guessed eligible/ineligible.

\==================================================
15\. PROGRESSIVE PROFILING
==========================

Do not force a long onboarding form.

Preferred flow:

preset
→ immediate useful opportunities
→ identify missing eligibility information
→ request only relevant profile fields
→ recompute eligibility

Example:

조건 확인 필요

다음 정보가 필요합니다.

- 대표자 연령
- 지역

\==================================================
16\. PROGRAM SCOPE
==================

Default useful opportunity scope:

- 사업화 지원
- 창업경진대회
- incubation
- acceleration
- investment-linked programs
- office/workspace/incubation space
- global expansion
- market entry
- education
- mentoring
- consulting

Generic policy loans and generic unrelated R&D should not dominate the default
feed.

\==================================================
17\. DATA COLLECTION STRATEGY
=============================

Use layered discovery.

Priority:

1. official APIs
2. RSS / Atom
3. HTML sources
4. legitimate JS-rendered public sources where necessary
5. search discovery adapter where configured
6. attachments/documents

K-Startup and 기업마당 remain first-class backbone sources.

Existing university/public/accelerator/foundation sources remain long-tail
adapters.

Do not bypass CAPTCHA, access control, anti-bot protection, or explicit site
restrictions.

A blocked source is a monitored failure.

\==================================================
18\. DOCUMENTS ARE FIRST-CLASS EVIDENCE
=======================================

Support attachments where technically practical:

- HTML
- PDF
- HWP
- HWPX
- DOCX

Do not assume the visible webpage contains the full eligibility rules.

Store document provenance and extraction status.

If parsing fails:

- preserve metadata
- preserve original link
- mark extraction failure
- do not invent content
- allow UNVERIFIABLE where critical evidence is unavailable

\==================================================
19\. NORMALIZED PROGRAM MODEL
=============================

Programs should retain canonical structured information such as:

- title
- organization
- program type
- status
- application period
- deadline type
- region
- target
- benefits
- support amount
- official URL
- application URL
- source IDs
- provenance
- current version

Dates should be interpreted in Asia/Seoul.

Closed opportunities should not appear as ordinary current recommendations.

\==================================================
20\. PROGRAM VERSIONING
=======================

A program is not immutable merely because title/URL remain the same.

Track meaningful changes including:

- deadline extension
- eligibility change
- benefit change
- application URL change
- document replacement
- status change

Preserve historical versions.

\==================================================
21\. REQUIREMENT EXTRACTION
===========================

Preferred evidence order:

1. structured official API data
2. official HTML detail
3. official attachment

Unstructured conditions may be converted into a strict requirement schema by
AI.

Requirement examples:

business\_status
business\_age\_months
founder\_age
region
student\_status
team\_size
product\_stage
revenue
investment\_received
industry
applicant\_type
prior\_support\_restrictions

Every extracted rule should preserve evidence where possible.

AI extraction must pass schema validation.

No invented requirements.

\==================================================
22\. ELIGIBILITY ENGINE
=======================

Preserve internal states:

ELIGIBLE
NEEDS\_INFO
INELIGIBLE
UNVERIFIABLE

Rules:

INELIGIBLE
→ confirmed mandatory requirement fails

NEEDS\_INFO
→ no confirmed failure, but required user/team information is unknown

ELIGIBLE
→ all required known conditions are satisfied

UNVERIFIABLE
→ critical program evidence cannot be reliably determined

The user-facing UI may group UNVERIFIABLE with "조건 확인 필요", but retain the
internal distinction.

LLM output must not override deterministic hard failures.

Eligibility must remain explainable.

\==================================================
23\. RECOMMENDATION ENGINE
==========================

Eligibility and recommendation are separate.

First:

Can this team apply?

Then:

How useful/relevant is it?

Possible ranking factors:

- stage fit
- applicant fit
- preferred support type
- benefit
- global relevance
- deadline runway
- source/data completeness

AI may generate:

- summary
- recommendation rationale
- suggested next action
- semantic relevance

Do not let AI override INELIGIBLE.

Avoid regenerating explanations on every page request.

Store and reuse results.

\==================================================
24\. MULTI-TEAM SUPPORT
=======================

A member may participate in multiple Radar teams.

The active team should be selectable.

Same program:

Team A
→ ELIGIBLE

Team B
→ INELIGIBLE

must be supported.

GFC's existing public.teams and Radar teams remain conceptually separate unless
an explicit optional mapping is needed.

Do not hard-couple them.

\==================================================
25\. AUTOMATION MODEL
=====================

Normal operation must be automatic.

Recommended conceptual schedule:

daily ingestion
→ discover new/changed opportunities
→ process documents
→ update programs
→ evaluate relevant teams
→ update recommendations

weekly digest
→ send useful opportunity summary

deadline checks
→ D-7 / D-3 where configured

Exact cron timing should be centralized/configurable.

Collection frequency and notification frequency are different concerns.

\==================================================
26\. GITHUB ACTIONS
===================

GitHub Actions remains the preferred execution environment for scheduled and
manual StartupRadar batch work unless there is a demonstrated technical reason
otherwise.

Required:

- concurrency control
- explicit failure status
- no silent failure-as-empty-result
- deterministic runtime configuration
- secrets stored outside repository
- no user profile changes through git commits

V2 scheduling should remain disabled until real-data validation is completed.

\==================================================
27\. AI COST CONTROL
====================

Do not repeatedly analyze unchanged source data.

Use hashes/versioning/cache.

Conceptually:

same source/document content
→ no new AI extraction call

new content
→ analyze

materially changed content
→ analyze changed version

Eligibility should remain code-driven where possible.

Avoid LLM invocation for ordinary page loads.

\==================================================
28\. TELEGRAM ROLE
==================

Telegram is a notification channel.

It is NOT the primary configuration UI.

Keep:

- weekly digest
- high-fit alerts
- deadline reminders
- limited admin alerts

Existing legacy commands may remain temporarily during V1/V2 coexistence.

Do not make /stage the long-term primary team configuration path.

\==================================================
29\. SOURCE HEALTH
==================

Admins must be able to distinguish:

"No relevant programs"

from:

"Collection failed."

Track at minimum:

- last attempt
- last success
- discovered count
- fetched count
- parsed count
- failures
- reason
- latency where useful

Do NOT claim monitored source success rate equals total Korean market coverage.

\==================================================
30\. CURRENT FRONTEND IMPLEMENTATION
====================================

Preserve the already implemented GFC routes where appropriate:

/notice
/notice/:id
/notice/radar/:id
/notice/admin/new
/notice/admin/:id
/radar/settings
/radar/admin

Do not create a second independent member dashboard unless required by a
specific technical constraint.

Use the existing GFC:

- React/Vite stack
- auth
- header/footer
- navigation
- styling conventions
- access model

\==================================================
31\. FRONTEND DATA ACCESS REFACTOR
==================================

The current implementation may still assume:

VITE\_RADAR\_API\_URL
→ hosted Python API

Audit and reduce this dependency.

For each current frontend request decide:

DIRECT SUPABASE
SAFE VIEW/RPC
ASYNC BACKEND JOB
PYTHON API REQUIRED

Prefer the simplest architecture that preserves:

- RLS
- explainability
- responsiveness
- security
- maintainability

The absence of VITE\_RADAR\_API\_URL must no longer block completion of all
possible frontend work.

The public GFC notice experience must work independently of Radar backend
availability.

If Radar temporarily cannot calculate a new result, present an honest pending
or unavailable state rather than failing the entire /notice page.

\==================================================
32\. PRODUCTION DATABASE SAFETY
===============================

The shared Supabase project is production infrastructure.

Before every new DDL migration:

- inspect current objects
- inspect conflicts
- inspect DROP/destructive ALTER
- inspect grants
- inspect policies
- inspect auth impact
- inspect GFC regression risk

Prefer additive migrations.

Never casually use migration repair or blanket db push across the shared
migration ledger.

Do not alter existing GFC objects unless genuinely necessary and explicitly
justified.

\==================================================
33\. EXISTING GFC SECURITY ISSUES
=================================

Do not broaden this Goal into unrelated refactoring of all historical GFC
security findings.

However:

- do not add new avoidable insecure patterns
- do not add broad authenticated EXECUTE grants
- avoid unnecessary SECURITY DEFINER RPCs
- explicitly authorize privileged operations
- fix only existing issues that directly block safe StartupRadar integration

Report unrelated legacy findings separately.

\==================================================
34\. CURRENT DEPLOYMENT STATE
=============================

Treat the current state as:

IMPLEMENTED IN BRANCHES
\+
SHARED DB MIGRATIONS APPLIED
\+
AUTOMATED TESTS PASSING
\+
NOT YET PRODUCTION CUTOVER

Do not misrepresent preview/fixture/browser mock success as real operating
end-to-end validation.

Do not merge to main or enable V2 scheduling simply because local/CI tests pass.

\==================================================
35\. IMMEDIATE NEXT WORK
========================

Continue from the current checkpoint in this order.

PHASE A — REMOVE FALSE HOSTING BLOCKER

1. Audit all current Python API endpoints.
2. Audit all VITE\_RADAR\_API\_URL frontend calls.
3. classify each endpoint by Section 4.
4. convert safe/simple member data paths to Supabase/RLS where appropriate.
5. keep only genuinely server-required functionality.
6. do NOT wait for a generic Python hosting project before progressing.

PHASE B — REAL SOURCE CONNECTION

Connect real credentials/configuration where available:

- K-Startup
- 기업마당
- Anthropic
- permitted long-tail sources

Never expose secrets.

Run actual ingestion against staging-disabled V2 state.

Verify:

- discovery
- details
- documents
- normalization
- requirements
- eligibility
- recommendations
- source failures

PHASE C — REAL ACCOUNT / BROWSER VERIFICATION

Using legitimate test accounts or controlled production-safe accounts verify:

anonymous
authenticated external
verified member
admin

Test actual deployed/preview environment, not only fixture mocks.

Verify:

- login
- member recognition
- Radar denial/allow
- notice visibility
- team access
- profile update
- team switch
- evidence
- admin notice operations
- mobile

Do not change unrelated real users.

PHASE D — REAL DATA FLOW

Demonstrate at least one actual path:

real external source
→ StartupRadar ingestion
→ Supabase
→ real GFC member page
→ program detail
→ eligibility evidence

without fixture data.

PHASE E — NOTIFICATION VALIDATION

Use approved test recipients.

Verify:

- weekly-style digest generation
- high-fit notification
- D-day reminder
- duplicate prevention
- partial delivery behavior
- preference enforcement

Do not message arbitrary production recipients.

PHASE F — V1/V2 PARALLEL RUN

Run V1 and V2 for the same defined comparison window.

Compare:

- programs discovered
- V1-only
- V2-only
- duplicate rate
- missed opportunities
- deadline correctness
- eligibility disagreements
- source failures
- notification behavior

Investigate disagreements.

PHASE G — CUTOVER PLAN

Only after evidence from real operation:

report whether V2 is ready.

Do not automatically cut over merely because tests pass.

\==================================================
36\. PYTHON SERVER DECISION GATE
================================

At the end of Phase A explicitly report:

PYTHON API STATUS

One of:

A. NOT REQUIRED
All necessary member-facing behavior is handled by Supabase + batch worker.

B. LIMITED API REQUIRED
Only listed endpoints require server execution.

C. FULL API STILL JUSTIFIED
A hosted Python service remains structurally necessary.

For B or C include exact reasons.

Only then choose hosting.

Do NOT choose Railway/Render/etc before this decision.

\==================================================
37\. REAL SOURCE CREDENTIALS
============================

Do not fabricate credentials.

If a real external key is unavailable:

- implement and validate everything possible
- report exact missing secret
- report exact place to configure it
- do not block unrelated implementation

Never ask the user to paste secret values into normal chat if they can instead
be configured directly in the relevant runtime/secret manager.

\==================================================
38\. TEST REQUIREMENTS
======================

Keep all existing tests green.

Add/update tests where architecture changes.

At minimum ensure coverage for:

ACCESS

anonymous
→ public notice yes
→ member notice no
→ Radar no

authenticated external
→ public notice yes
→ Radar no

member
→ member notice yes
→ Radar yes

admin
→ notice admin yes

TEAM ISOLATION

member A
→ own team allowed
→ unauthorized team denied

PRESETS

Stage 0
→ works without optional data

ELIGIBILITY

same program
→ different teams
→ different result

DOCUMENT FAILURE

parse fail
→ not falsely used as eligibility evidence

DATES

Asia/Seoul
rolling
fixed
closed
D-7
D-3

DEDUP/VERSION

same program multi-source
URL changes
deadline extension
material change

NOTIFICATION

actual sent items only
duplicate protection
partial failures
update notification

FAILURES

API empty != API failure
AI failure != no programs
document failure typed

REGRESSION

existing GFC:
login
projects
profiles
auction/current active functions

\==================================================
39\. LIVE VALIDATION REQUIREMENTS
=================================

Before declaring READY, provide evidence of:

1. actual non-fixture external source ingestion

2. actual Supabase persistence

3. actual member access through GFC web

4. actual non-member denial

5. actual team-specific eligibility

6. actual source failure visibility

7. actual program evidence/document path

8. actual OAuth/member role flow

9. actual notification test to approved receiver

10. actual V1/V2 comparison

Synthetic/fixture tests remain useful but do not satisfy these requirements
alone.

\==================================================
40\. PRODUCTION CUTOVER CRITERIA
================================

Do not enable V2 production automation until:

- real source flow works
- auth/RLS live validation passes
- no critical regression exists
- notification idempotency is proven
- V1/V2 comparison is reviewed
- critical missing source/API failure behavior is understood
- manual notices work on production domain
- deployment architecture is finalized

Then prepare a cutover proposal.

Do not perform irreversible cutover without explicit approval.

\==================================================
41\. V1 RETIREMENT
==================

V1 remains available until V2 cutover is approved.

Do not delete V1 code/workflows/history during validation.

After approved cutover:

- disable V1 schedule
- preserve rollback ability
- monitor V2
- retire V1 only after a defined stability window

\==================================================
42\. COST MODEL
===============

Track potential cost drivers.

AI:

- Anthropic extraction/recommendation
- avoid unchanged reanalysis

Supabase:

- shared DB
- storage
- auth
- data growth

GitHub Actions:

- scheduled ingestion runtime

Search provider:

- only if configured/needed

Python hosting:

- only if Section 36 concludes it is necessary

Telegram:

- no ordinary message fee assumed, but operational limits still apply

Do not create paid infrastructure unless technically justified.

\==================================================
43\. DOCUMENTATION
==================

Update documentation to describe the actual final architecture.

Document:

- ingestion flow
- shared Supabase model
- startup\_radar schema
- GFC notice model
- member authorization
- RLS
- five presets
- eligibility semantics
- requirement evidence
- document handling
- source adapters
- schedule
- cache/version logic
- notification flow
- environment variables
- adding a source
- deployment
- failure recovery
- V1/V2 migration
- Python API decision

Do not leave README describing obsolete architecture as current.

\==================================================
44\. REQUIRED FINAL REPORT FORMAT
=================================

At every major checkpoint report clearly:

CURRENT PHASE

FILES / REPOSITORIES CHANGED

COMMITS / PRS

DATABASE CHANGES

SUPABASE SECURITY / RLS

PYTHON API STATUS

LIVE SOURCE STATUS

GFC FRONTEND STATUS

AUTH / ROLE LIVE VALIDATION

TELEGRAM STATUS

TEST RESULTS

CI RESULTS

PRODUCTION REGRESSION

V1/V2 PARALLEL STATUS

EXTERNAL SETUP STILL REQUIRED

KNOWN LIMITATIONS

NEXT STEP

CUTOVER STATUS

Never label the project complete unless real operational acceptance criteria
have been met.

\==================================================
45\. IMPORTANT NON-GOALS
========================

Do NOT:

- rebuild completed V2 work from zero
- create a new Supabase project
- create a second GFC authentication system
- expose service-role credentials
- merge Radar automatic items into manual notice rows
- treat login as verified membership
- use frontend hiding as the only access control
- force detailed profiling before Stage 0 value
- let AI override deterministic ineligibility
- claim literal nationwide 100% support-program coverage
- bypass anti-bot restrictions
- silently swallow ingestion failures
- store user profile configuration in Git
- require a permanent Python HTTP API without evidence
- provision paid hosting merely to satisfy an old architecture assumption
- enable V2 production scheduling before live verification
- terminate V1 before approved cutover

\==================================================
46\. DECISION PRIORITY
======================

If implementation details conflict, use this priority.

1. Latest explicit decisions in this Goal
2. Existing production safety
3. Verified external/source facts
4. Current implemented V2 architecture
5. Previous Goal assumptions
6. README/legacy documentation

Never preserve an obsolete design assumption merely because old code already
implements it.

At the same time, prefer incremental adaptation over unnecessary rewrite.

\==================================================
47\. DEFINITION OF DONE
=======================

StartupRadar 2.0 is DONE only when:

A GFC member can use gfc-startup.com to:

- view GFC notices
- view StartupRadar opportunities
- select/manage a Radar team
- use Stage 0 without full profiling
- understand eligibility
- inspect evidence
- see useful recommendations

while:

an external user can:

- read PUBLIC GFC notices
- NOT retrieve StartupRadar private data

and:

the system automatically:

- collects actual startup-support opportunities
- processes official details/documents
- versions changes
- evaluates teams
- updates recommendations
- tracks failures
- sends configured notifications

and:

operators can:

- publish manual notices
- inspect source/ingestion health
- understand failures

and:

all of the above has been validated against:

- real external sources
- real Supabase
- actual authenticated roles
- actual deployed GFC UI
- approved test notifications
- V1/V2 parallel comparison

without breaking the existing GFC production service.

\==================================================
48\. CORE PRINCIPLE
===================

Optimize for:

"Can a GFC founder reliably find an opportunity they can actually apply to,
understand the evidence, and act on it before the deadline?"

Not:

"How many pages did we scrape?"

Not:

"Did we successfully deploy another server?"

Not:

"How many features did we implement?"

Correctness, evidence, access control, operational reliability and actual
founder usefulness are the priority.