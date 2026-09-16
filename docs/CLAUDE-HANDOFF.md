# StartupRadar / GFC — audited handoff

Read-only audit performed 2026-09-16 by Claude Code taking over from the previous engineering
agent. No application code, migration, secret or production run was changed **by the audit**.

> **Status update — 2026-09-16, after the audit.** The three gaps this audit found in §10, §11 and
> §12 have since been fixed on branch `claude/gfc-relevance-actionability-v1-1` and the two live
> articles were corrected in place. Those three sections below are retained as the original
> evidence of the defect; read §19 at the end for what changed. Everything else still stands.

Verification sources: `origin/main` of both repositories (extracted with `git archive`, not the
possibly-stale local working tree) and **read-only** SQL against the shared Supabase project
`etvffzxqdgblvkfdikwl`. Mutable production facts are marked *verified as of 2026-09-16*.

`CLAUDE.md` holds the short invariants. This file holds the evidence.

---

## 1. Repository state (verified as of 2026-09-16)

| | startup-radar | GFC-startup.com |
| --- | --- | --- |
| Local path | `~/OneDrive/Desktop/startup-radar` | `~/OneDrive/Desktop/GFC/GFC-startup.com` |
| Local branch | `codex/production-hardening-20260914` | `main` |
| Local HEAD | `bde81b7` | `23644d2` |
| `origin/main` | **`1608344`** | `23644d2` |
| Working tree | clean (untracked `.claude/` only) | clean (untracked `.claude/worktrees/` only) |

**The local startup-radar checkout is 6 commits behind `origin/main`** and does not contain the
first-publication baseline work. Always `git fetch` and read `origin/main` before trusting the
local tree. `origin/main` is what GitHub Actions runs.

Commits on `origin/main` missing locally (oldest → newest):

```
5d89731 fix: bound weekly collection without masking source failures
35d928c feat: add bounded official channels to weekly briefing
4edd29b fix: defer unstable channel and tighten weekly source scope
aba8f60 fix: replace unavailable weekly channel with MARU notices
5e2d566 fix: split first weekly publication from baseline archive
1608344 chore: align baseline migration with production history
```

**Draft PRs — reference only, do not merge.** Both are branch
`feat/weekly-admin-controls` (radar `de36fc0`, GFC `4693e45`). The radar branch adds
`institutions.json` (1046 lines), `radar/discovery.py`, `radar/opportunity_store.py`,
`radar/adapters/opportunities.py`, `weekly_schedule.py`, three migrations and 20-institution
expansion — i.e. daily discovery, an opportunity catalogue and institution administration. This
is precisely the scope the current product excludes. Adapters and date parsing were already
selectively ported into `radar/adapters/weekly_direct.py` and `radar/opportunity_facts.py`.

## 2. Instruction files read

- `startup-radar/README.md`
- `startup-radar/docs/` — `WEEKLY-BRIEFING.md`, `ARCHITECTURE.md`, `DEPLOYMENT.md`,
  `SOURCES.md`, `PRODUCTION-OPERATIONS.md`, `OPERATIONS.md`, `PRODUCTION-HARDENING.md`,
  `GFC-OPERATING-GOAL.md`, `V2-SPEC.md` (headers/classification)
- `startup-radar/.claude/settings.local.json`, `GFC-startup.com/.claude/settings.local.json`

**No `AGENTS.md`, `AGENT.md`, `CONTRIBUTING.md` or pre-existing `CLAUDE.md` exists in either
repository, at any level, tracked or untracked** (checked via `find` and `git ls-files`).
`GFC-startup.com` has no `README.md` at all. Searched parent directories too; nothing
hierarchical applies. This handoff therefore establishes the first agent instructions.

## 3. Document currency

**Current contract:** `docs/WEEKLY-BRIEFING.md` (line 3: "This supersedes the
production-hardening completion priorities on 2026-09-14"), `README.md`, `docs/SOURCES.md`
(official API contracts, checked 2026-09-15), `docs/DEPLOYMENT.md`,
`weekly-direct-sources.json`, `.github/workflows/startup_radar_v2.yml`.

**Stale — actively misleading:**
- `docs/ARCHITECTURE.md:3` — "Production cutover and V2 schedules remain disabled; V1 is
  retained." Production has published two articles.
- `docs/PRODUCTION-OPERATIONS.md:20,23` — "GitHub cron은 `17 * * * *`" and "주간 요약: 화요일
  15:17 KST". The only production calendar is `0 6 * * 2` (Tue 15:00 KST); hourly TICK is not on
  this path.

**Historical:** `PRODUCTION-HARDENING.md` (self-labelled "Status: IN PROGRESS. This is not
production acceptance or the current runbook"), `V1-AUDIT.md`, `V2-SPEC.md`, `V2-PROGRESS.md`,
`V2-SETUP.md`, `LEGACY-V1-README.md`, `COMPLETION-AUDIT.md`, `GFC-OPERATING-GOAL.md`,
`GFC-NOTICE-INTEGRATION*.md`, `GFC-SHARED-DEPLOYMENT-DECISION.md`, `PYTHON-API-DECISION.md`,
all `*-VERIFICATION.json` snapshots.

## 4. Architecture

```
GitHub Actions (startup_radar_v2.yml, Tue 06:00 UTC, gated by vars.RADAR_V2_ENABLED)
  └─ python -m radar.cli weekly [--check-sources] [--revision-note X] [--deliver]
       └─ radar.weekly.run_weekly
            ├─ executions.claim_execution('WEEKLY')      durable single-owner lock
            ├─ weekly_scope.weekly_sources(...)          GFC_WEEKLY_V1 bounded window
            ├─ ingestion.ingest(..., structured_only=True)   no AI / OCR / eligibility
            │    ├─ adapters.official.KStartupApiAdapter / BizInfoApiAdapter
            │    └─ adapters.weekly_direct.OfficialChannelAdapter  (8 approved channels)
            ├─ weekly.build_briefing(...)                NEW/UPDATE diff + publish
            └─ weekly.announce(...)                      one Telegram post per chat
                                   ↓
        Supabase etvffzxqdgblvkfdikwl / schema startup_radar
                                   ↓
        SECURITY INVOKER RPC gfc_radar_weekly_briefing(s)  (my_role() ∈ member/admin)
                                   ↓
        GFC-startup.com  /notice  ·  /notice/weekly/:id
```

Legacy V1 (`crawler.py`, `core/analyzer.py`, `main.py`, `notifier.py`) is **retained but not on
the weekly path**. Its `relevance_score` prompt is V1-only — do not mistake it for a current
editorial filter.

## 5. Weekly flow, exactly as coded

`radar/weekly.py: build_briefing()`

1. `week_window(at)` → Seoul Monday..Sunday.
2. Advisory lock `782394203`; load the current week's `WEEKLY` row `for update`.
3. If already `PUBLISHED` and no `--revision-note` → return existing ID, no rewrite.
4. `known` = latest `material_hash` per `program_id` from **all** previously published items
   where `b.week_start < start` **or** `b.publication_kind = 'INITIAL_BASELINE'`.
5. For each collected program: skip if `status == 'CLOSED'` or no `official_url`; skip if the
   material hash equals `known[pid]` (→ UNCHANGED items are dropped entirely, never rendered);
   otherwise mark `UPDATE` if `pid in known` else `NEW`.
6. Order by `application_end_at` (nulls sort last via `'9999'`), then title, then id.
7. Upsert briefing on `(week_start, publication_kind)`, replace items, set `PUBLISHED` with
   `published_at = coalesce(published_at, now())`.

`MATERIAL` (the change fingerprint) = title, organization, support_summary, applicant_summary,
application_start_at/end_at, both precisions, deadline_type, official_url, application_url,
attachments. Attachment identity uses advertised API URLs only — a silently replaced binary at
an unchanged URL is undetectable by design.

## 6. Source coverage (verified as of 2026-09-16, `startup_radar.sources`)

**Backbone:** `kstartup` (KSTARTUP, enabled), `bizinfo` (BIZINFO, enabled).
Both show `last_failure_reason = PAGE_LIMIT` — this is the *expected* declared bounded-scope
marker, not an outage.

**Direct official channels — 8 enabled, all `policy_status=APPROVED`, all succeeded 2026-09-15:**
`weekly-yonsei-notices`, `weekly-postech-aif-notices`, `weekly-gyeonggi-unicornbridge`,
`weekly-koef-recruitment`, `weekly-asan-notices` (아산나눔재단/MARU), `weekly-orange-farm`,
`weekly-antler-residency`, `weekly-lotte-recruitment`.

**Deferred/disabled:** `weekly-korea-opportunity-board` (Korea Univ. Sejong, `LIST_PARSE`),
`weekly-samsung-clab-newsroom` (`ROBOTS_FETCH_TIMEOUT`), legacy `korea-startup-html`.
SNU excluded on published reuse terms.

This matches the previous operator handoff exactly. The registry file
`weekly-direct-sources.json` is only a **seed**; the DB `sources` table is production truth
(`radar.cli seed-sources --file weekly-direct-sources.json` applies it).

Bounded scope is one listing page or one fixed section per channel, `max_records` 10–30, 3 MB
HTML cap, 120k char detail cap, 1 s spacing, 60 requests / 240 s per channel. **8 channels is
not 8 open programs**, and a healthy channel legitimately yields zero.

## 7. Date semantics by source — the critical audit

Five distinct concepts must never be conflated:
A official publication date · B application start · C application deadline ·
D crawler observation · E DB row timestamps.

### K-Startup (`adapters/official.py: KStartupApiAdapter.normalize`)

| | Field | Notes |
| --- | --- | --- |
| A publication | **NOT AVAILABLE** | No notice-publication field is read from the API contract. |
| B start | `pbanc_rcpt_bgng_dt` → `application_start_at` | *receipt* begin, i.e. application open |
| C end | `pbanc_rcpt_end_dt` → `application_end_at` (`time.max`) | |
| D observation | `Candidate(..., now().isoformat())` | discovery time only |

Precision is `DATE`, upgraded to `DATETIME` only by `kstartup_period_time()`, which reads a
labelled `신청기간`/`접수기간` clock from the portal detail body and accepts it only if exactly
one time is found. **There is no reliable official publication timestamp for K-Startup in the
current contract.**

### BizInfo (`BizInfoApiAdapter.normalize`)

| | Field | Notes |
| --- | --- | --- |
| A publication | `creatPnttm` — **present in raw_metadata but NOT normalized** | used *only* by the baseline-split SQL |
| B/C | `parse_period(reqstBeginEndDe or reqstDt)` | ISO or compact `YYYYMMDD ~ YYYYMMDD`; both null unless the full range parses |
| D observation | `now()` at discovery | |

`parse_period` requires a *complete* two-sided range; a one-sided or free-text value yields
`(None, None)` and `deadline_type='UNKNOWN'`.

### Direct HTML channels (`weekly_direct.py` + `opportunity_facts.py`)

| | Behaviour |
| --- | --- |
| A publication | **Not extracted as a publication date.** `period_year_selector` yields only a *year context* (`period_year_context`) used to disambiguate short dates. |
| B/C | `labeled_period()` — only from an explicit `모집/신청/접수/지원 기간` label, or `상시/연중` rolling. |
| Guards | An event date is never a deadline (`행사·사업·운영 기간` is split off). A year is **never** inferred from today's clock — only from the notice's own explicit year or an explicitly dated range. `end < start` → both discarded. |

So: for **every** active source, what StartupRadar knows is the **application period**, not the
official posting time. `creatPnttm` is the single exception and it is used in exactly one place.

## 8. NEW / UPDATE semantics

**NEW currently means "this `program_id` has never appeared in a previously published
StartupRadar article", not "officially published within the current week."**

Traced at `radar/weekly.py:73-84`: `known` is built from published `weekly_briefing_items`, and
`change_type = 'UPDATE' if pid in known else 'NEW'`. No date comparison participates. A program
posted by the institution months ago that StartupRadar first observes this week is labelled
`신규`.

UI wording (`GFC-startup.com/src/pages/WeeklyBriefingPage.jsx:34`) renders a bare
`{item.change_type === 'UPDATE' ? '변경' : '신규'}` badge, and `NoticePage.jsx:51` shows
`신규 N건 · 변경 M건`. Neither qualifies that "신규" means *newly detected by StartupRadar*. A
member will reasonably read it as *newly announced*. This is a wording/semantics mismatch, not a
code bug.

The one-time baseline split is the **only** place where an official-date rule is applied.

## 9. Initial baseline semantics

`supabase/migrations/20260915091742_first_publication_baseline.sql`.

- Adds `publication_kind ∈ (WEEKLY, INITIAL_BASELINE)`, `display_start/display_end`
  (`display_end = display_start + 6`), `snapshot_date`; replaces the `week_start` unique key with
  `unique(week_start, publication_kind)`; partial unique index `weekly_one_initial_baseline`
  allows **at most one** baseline ever.
- `split_initial_publication(p_id, p_reason, p_expected_count)` — operator-only
  (`service_role`), `security invoker`, no collection, no program/version edits, no Telegram.
- Preconditions: published `WEEKLY` row; it must be the *only* briefing; **no prior
  announcement**; count must equal `p_expected_count` and `item_count`, and `new_count` must
  equal the total (NEW-only). Idempotent — a repeat returns the recorded result with
  `unchanged:true`.
- Window = the seven completed Seoul days **before** the publication date
  (`window_end = published_at::date - 1`, `window_start = window_end - 6`).
- Partition rule per item: `coalesce(min BizInfo creatPnttm observed at or before published_at,
  application_start_at when precision ∈ DATE/DATETIME)`. Inside the window → stays `WEEKLY`;
  otherwise → moved to the baseline. Missing/invalid → baseline. Observation/insert/version
  timestamps are explicitly excluded from this decision.
- Preserves weekly ID, operational week and first `published_at`; increments `revision`. Writes
  `admin_audit` action `INITIAL_PUBLICATION_SPLIT` with the previous briefing, previous items,
  per-program date evidence (`evidence_kind`: `BIZINFO_OFFICIAL_PUBLICATION` vs
  `OFFICIAL_APPLICATION_START_OR_UNKNOWN`), both IDs/counts and `telegram_sent: false`.
- The baseline cannot be announced: `weekly.py:136` returns `{'state':'BASELINE_ARCHIVE'}`.
- Both kinds feed `known` history in step 4 of §5, so baseline items never resurface as 신규.

**Production state (verified as of 2026-09-16):** the split has been executed once
(`admin_audit` count = 1). Exactly two rows exist:

| kind | items | new | week | display / snapshot | published_at (UTC) | rev |
| --- | --- | --- | --- | --- | --- | --- |
| `WEEKLY` | 83 | 83 | 2026-09-14..20 | 2026-09-08 ~ 2026-09-14 | 2026-09-15 08:35:11 | 2 |
| `INITIAL_BASELINE` | 123 | 123 | 2026-09-14..20 | snapshot 2026-09-15 | 2026-09-15 08:35:11 | 1 |

206 items total; 289 programs stored; 34 ingestion runs.

## 10. Actionability gap (current behaviour — not fixed)

`radar/dates.py: program_status()` returns `CLOSED` (past end) → `UPCOMING` (before start) →
`OPEN` (rolling, or has an end date) → `UNKNOWN` (no end date, not rolling).

`radar/weekly.py:81` filters **only** `status == 'CLOSED'` (plus missing `official_url`).
Consequence, for the backbone K-Startup/BizInfo sources:

| Case | Published today? |
| --- | --- |
| Already expired | No — correctly excluded |
| Expires in < 24 h | **Yes** |
| Expires in < 48 h | **Yes** |
| Expires in < 72 h | **Yes** |
| Deadline unknown | **Yes** (`UNKNOWN`, sorts last) |
| Not yet open (`UPCOMING`) | **Yes** |

Direct channels are stricter — `opportunity_facts.weekly_decision()` excludes `CLOSED` and
`UPCOMING` and sends anything not explicitly `OPEN` to a `REVIEW` bucket — but that gate does
not apply to the two backbone sources, which supply most of the volume.

Note `korean_date(value, end=True)` sets `time.max`, so a deadline of *today* is still `OPEN`
until 23:59:59 Seoul — a Tuesday 15:00 publication gives such an item ~9 hours of lead time.

**Measured on the live WEEKLY issue (83 items, verified as of 2026-09-16):**
0 already expired · 5 expiring within 24 h of publication · 8 within 48 h · 11 within 72 h ·
4 with unknown deadline. So ~13 % of the published set had under three days of runway.

**There is no minimum lead-time gate anywhere in the codebase.**

## 11. GFC relevance gap (current behaviour — not fixed)

**No `GFC_RELEVANT` / `CONDITIONAL` / `OUT_OF_SCOPE` classification exists in any repository
file** (grepped across `*.py`, `*.sql`, `*.json`). The weekly production path performs **no**
editorial filtering:

- K-Startup and BizInfo records go straight to `decision = 'ACCEPTED'` (`ingestion.py:57`) with
  no classification at all.
- `program_types` is captured (`supt_biz_clsfc`, `pldirSportRealmLclasCodeNm`) but is **not** in
  `weekly.MATERIAL` and is never filtered on.
- `radar/eligibility.py`, `radar/recommendations.py` and team profiles exist but are **not
  imported** by `radar/weekly.py` and are skipped by `structured_only=True`.
- Direct channels get `opportunity_facts.classify()` (`category`, `participation`, `stages`)
  plus the `EXCLUDED_TITLE` regex — but that only answers *"is this a recruitment notice?"*, not
  *"is this relevant to a student founder?"*, and it does not touch the backbone sources.

**Evidence from the live member-facing issue** (first 40 of 83 items, verified 2026-09-16) —
these are all currently visible to GFC members:

- `[경기] 광명시 2026년 하반기 착한가격업소 신규 모집` — merchant price-pledge designation
- `[울산] 중구 2026년 소상공인 카드수수료 지원사업` — small-merchant card-fee subsidy
- `[경남] 2026년 2차 뿌리기업 맞춤형 제조로봇 공정연구 및 보급사업` — mature manufacturing
- `[경북] 포항시 2026년 철강산업 전환성장 사업재편 컨설팅` — steel-industry restructuring
- `[충남] 서산시 2026년 석유화학 산업 기업 모집` — petrochemical
- `2026년 SVC Seoul 인턴십 프로그램 학생인턴 모집공고` — internship posting
- `[서울과학기술대학교] 레이저커팅기 장비교육` — equipment training
- `[서울] 2026년 홍콩 메가쇼 참가기업 모집`, `베트남 시장개척단`, `대만국제식품산업박람회` —
  export/trade-show missions for established SMEs
- `[인천] 뿌리청년 사내맛남 뿌리미(味)래 푸드트럭 참여기업 추가모집`

Genuinely on-mission items in the same sample: 스타트업 법률지원사업, 서강비즈니스센터 입주기업,
스타트업 96 입주 예비창업자, 오픈이노베이션 프로그램, TECHFEST 통합관, 청년 창업자 임차료 지원,
청년 창업가 네트워킹.

By inspection roughly a quarter of the published set matches the stated GFC audience. This is
the single largest divergence between the product definition ("curated weekly set of actionable
startup opportunities") and current behaviour ("bounded recent slice of two national portals").

## 12. Deduplication state

`radar/database.py: save_program()` — three deterministic tiers under advisory lock `782394201`:

1. `(source_id, source_program_id)` — same source, same publisher ID.
2. Exact `normalize_url(official_url)` match **and** exact normalized title **and** exact
   normalized organization **and** no conflicting publisher ID on that source. Exactly one match
   merges; more than one sets `weekly_duplicate_conflict`.
3. Exact `application_start_at` **and** `application_end_at` **and** exact title/org — but only
   when the incoming record has `weekly_direct_facts` **or** the candidate already has a
   `weekly_direct` source.

Otherwise a new program is inserted; `duplicate_confidence()` scores are recorded for human
review and **never** auto-merge.

**Gap:** tier 3 requires a direct channel on at least one side. K-Startup and BizInfo are both
non-direct, and their canonical URLs differ (`k-startup.go.kr` vs `bizinfo.go.kr`), so tier 2
also fails. **A program cross-posted to both national portals becomes two programs and therefore
two member-facing weekly items.**

Confirmed in production (verified as of 2026-09-16) — the TECHFEST case is live in the current
WEEKLY issue:

| title | items | distinct program_ids | hosts |
| --- | --- | --- | --- |
| 베트남 테크페스트(TECHFEST 2026) K-스타트업 통합관 참가기업 모집(공)고 | 2 | 2 | `www.bizinfo.go.kr`, `www.k-startup.go.kr` |

It is the only title-level duplicate across all 206 published items. Note the titles differ by
one character (`모집 공고` vs `모집공고`) and the organizations differ (`중소벤처기업부` vs
`창업진흥원장`), so even a title/org equality rule would not have merged them.

## 13. GFC web contract

- `src/App.jsx:50` routes `^/notice/weekly/([0-9a-f-]{36})$` → `WeeklyBriefingPage`;
  `/notice` → `NoticePage`.
- **Member-only twice over**: client `if (!isMember) return <LockedRadar/>`
  (`WeeklyBriefingPage.jsx:22`, `NoticePage.jsx:31,62`) *and* the RPC raising `42501` unless
  `my_role() ∈ ('member','admin')`. Anonymous/external accounts read nothing.
- `NoticePage` lists GFC manual notices and weekly articles in **separate** sections with
  independent pagination — no global merge (`noticeModel.feedSections`).
- **WEEKLY rendering:** header `display_start ?? week_start ~ display_end ?? week_end`, summary
  `신규 N건 · 변경 M건`, per-item `신규`/`변경` badge.
- **INITIAL_BASELINE rendering:** label `초기 자료`, `snapshot_date 기준 · item_count건`, and the
  change badge is suppressed (`data.publication_kind !== 'INITIAL_BASELINE' &&`).
- Per item: 운영기관 / 지원 내용 (700 char cap) / 신청 자격 (500 char cap) / 신청 마감
  (`formatDate(value, precision)` → `일정 확인 필요` when precision is `UNKNOWN`), then
  `공식 공고 보기` and `신청하기` links, both `https`-only via `safeSourceUrl()` and rendered
  only when the application URL differs from the official URL.
- Items render as one flat ordered list. **To show GFC relevance sections** you would need: a
  relevance field on `weekly_briefing_items.snapshot` (or a sibling column), exposure through
  `gfc_radar_weekly_briefing`, and grouping in `WeeklyBriefingPage.jsx:31-47` — plus a count
  breakdown in `NoticePage.jsx:51`.
- **Test-coverage gap:** `tests/fixtures/radar-migrations/` stops at
  `20260914093636_weekly_briefings.sql` and does **not** include the baseline migration.
  `tests/notice-access.test.js` has no weekly/briefing coverage at all. Only the Playwright
  `e2e/notice.spec.js` references `publication_kind`. Any schema change here needs the fixture
  refreshed first.

## 14. Telegram

`weekly.py: announce()`. Preconditions: briefing `PUBLISHED`; `publication_kind != INITIAL_BASELINE`;
subscription `enabled AND digest_enabled AND channel_health='HEALTHY'` and team preferences not
disabled. `distinct on (chat_id)` plus `unique(briefing_id, chat_id)` means one chat cannot be
posted twice through multiple teams. A committed `SENDING` claim precedes the network call;
`FAILED`/`UNCERTAIN`/`SENDING` are never auto-resent. Message = title, count, ≤3 examples, and
the member-only article URL (`briefing_url()` validates `RADAR_MEMBER_NOTICE_URL`, rejecting any
query/fragment). `--deliver` is additionally gated by `vars.RADAR_V2_DELIVERY_ENABLED`.

**Production state (verified as of 2026-09-16):** 2 subscriptions, **0 deliverable**, **0 rows in
`weekly_announcements`** — no Telegram announcement has ever been sent. `NO_SUBSCRIBERS` is
returned as a valid no-op. This is also why the baseline split's "no prior announcement"
precondition passed.

## 15. Handoff claim verification

| # | Claim | Verdict | Evidence |
| --- | --- | --- | --- |
| 1 | Production runs Tuesday 15:00 Asia/Seoul | **VERIFIED** | `startup_radar_v2.yml:5` `cron: '0 6 * * 2'` (06:00 UTC = 15:00 KST), gated by `vars.RADAR_V2_ENABLED` |
| 2 | Publishes one normal weekly briefing | **VERIFIED** | Upsert on `(week_start, publication_kind)`; published week is stable (`weekly.py:72`); DB holds exactly one `WEEKLY` row |
| 3 | One-time `INITIAL_BASELINE` exists for the first-run split | **VERIFIED** | Migration `20260915091742`; unique index `weekly_one_initial_baseline`; DB row 123 items, `snapshot_date` 2026-09-15; 1 `INITIAL_PUBLICATION_SPLIT` audit |
| 4 | Normal NEW detection is known-state based, not a publication-date guarantee | **VERIFIED** | `weekly.py:73-84` — `known` from published items; `'UPDATE' if pid in known else 'NEW'`; no date compare |
| 5 | BizInfo `creatPnttm` is official publication evidence in the initial split | **VERIFIED** | Migration lines 73-84; `coalesce(min(creatPnttm) …, application_start …)`, `evidence_kind = BIZINFO_OFFICIAL_PUBLICATION` |
| 6 | K-Startup normalized dates are application period, not notice publication | **VERIFIED** | `official.py:182-183` — `pbanc_rcpt_bgng_dt` / `pbanc_rcpt_end_dt` only; no publication field read |
| 7 | Excludes CLOSED but has no general 72-hour lead-time gate | **VERIFIED** | `weekly.py:81` filters only `CLOSED`; live issue has 11 items under 72 h and 4 unknown-deadline |
| 8 | No `GFC_RELEVANT/CONDITIONAL/OUT_OF_SCOPE` production filter yet | **VERIFIED** | No such identifier anywhere; backbone records hardcode `decision='ACCEPTED'` (`ingestion.py:57`) |
| 9 | Weekly collection does not depend on AI/OCR/team eligibility | **VERIFIED** | `ingest(structured_only=True)` → `extractor=None` (`ingestion.py:24`), no documents, `resolve_review` skipped (`:68`); `weekly.py` imports none of them |
| 10 | Telegram is one weekly announcement; zero subscribers is a valid no-op | **VERIFIED** | `announce()` `unique(briefing_id, chat_id)` + `distinct on (chat_id)`; `NO_SUBSCRIBERS` early return (`weekly.py:141`); production 0 deliverable, 0 announcements |

All ten claims verified. Two carry important nuance: **#2** — one *normal weekly* article, but
two published articles exist because of the one-time baseline; **#7** — direct channels *do*
exclude `UPCOMING` and quarantine unknown timing, so the gap is specific to K-Startup/BizInfo.

## 16. Production invariants that must not be broken

1. One weekly publication per Seoul week; one Telegram announcement; published weeks immutable
   except via explicit `--revision-note`.
2. At most one `INITIAL_BASELINE`; it must never announce; both kinds establish known history.
3. Weekly path stays free of AI, OCR, eligibility, recommendations and team refresh.
4. All-source failure never publishes or announces; `INCOMPLETE_EMPTY_COLLECTION` never publishes.
5. Member-only access via SECURITY INVOKER RPC + `my_role()`; no client writes; preserve GFC
   Auth/RLS and `public.gfc_notices` separation.
6. Auditability: `admin_audit` on revisions and the split; never erase evidence or versions.
7. Never infer unknown dates or eligibility; never treat crawler/DB timestamps as official
   publication dates; never infer a year from the current clock.
8. Deterministic identity only; no fuzzy auto-merge; never override conflicting publisher IDs.
9. Bounded scope stays declared and visible (`BOUNDED_WEEKLY_SCOPE`, `record_cap_reached`,
   `pagination_complete=false`); weekly runs never advance `last_successful_full_scan_at`.
10. Respect robots/host/redirect checks, size and rate budgets; no login, CAPTCHA or access
    workaround.

## 17. Files a future fix would likely touch

**Actionability (lead-time gate):** `radar/weekly.py` (`build_briefing` filter),
`radar/dates.py` (`days_left`/`program_status`), possibly `radar/opportunity_facts.py`
(`weekly_decision`), `docs/WEEKLY-BRIEFING.md`, `tests/test_weekly.py`.

**GFC relevance:** a new `radar/` classifier module; `radar/weekly.py` (`MATERIAL` and the item
loop); a migration adding a relevance column/field on `weekly_briefing_items` plus the
`gfc_radar_weekly_briefing(s)` RPCs; `GFC-startup.com/src/pages/WeeklyBriefingPage.jsx` and
`NoticePage.jsx`; `GFC-startup.com/tests/fixtures/radar-migrations/` (must be refreshed);
new tests both sides.

**Cross-portal dedup:** `radar/database.py` (`save_program` tier 3), `radar/identity.py`,
`tests/` — and note that changing identity retroactively affects `known`/NEW semantics and the
existing 206 published items, so it needs an explicit migration/audit plan.

**Caution:** `weekly_briefing_items.snapshot` is an immutable editorial snapshot and
`material_hash` drives NEW/UPDATE. Adding a field to `MATERIAL` will make **every** existing
program look `UPDATE`d on the next run. Any relevance field should live outside `MATERIAL`
unless that mass-update is intended.

## 19. What changed on 2026-09-16 (GFC Relevance v1.1 + actionability)

Implemented on `claude/gfc-relevance-actionability-v1-1` in both repositories, based on
`origin/main` (radar `1608344`, GFC `23644d2`).

**Code.** New `radar/actionability.py` (72-hour gate) and `radar/relevance.py` (deterministic
two-axis classifier, `gfc-v1.1`). `radar/identity.py` gained `cross_source_key` and
`deduplicate_publication`; `radar/database.py` gained a fourth, conservative cross-portal identity
tier; `radar/weekly.py` wires dedup → material change → actionability → relevance and writes the
published decision onto each item. Summary and Telegram wording moved from `신규` to `새로 확인`.

**Why deterministic and not an LLM.** The weekly path deliberately has no AI dependency, and that
reliability is worth more than marginal recall on a single weekly publication. A classifier that
can time out or invent eligibility would put the whole issue at risk. The decisive Korean signals
here (착한가격업소, 카드수수료, 인턴 모집, 뿌리기업, 액셀러레이팅, 데모데이, PoC) are highly
specific, so rules reach acceptable v1.1 quality without that risk, and every decision carries its
matched evidence for audit.

**Schema.** `20260916120000_gfc_relevance_and_actionability.sql` adds
`startup_radar.program_relevance` (keyed by `program_version_id, relevance_version`, outside
`weekly.MATERIAL`), three denormalized columns on `weekly_briefing_items`, the operator-only
`apply_publication_correction()` and the relevance fields on `gfc_radar_weekly_briefing`.
`20260916121000_gfc_relevance_backfill_function.sql` is generated by
`tools/export_relevance_sql.py`; `tests/test_relevance_sql_mirror.py` fails if it drifts. The two
implementations were cross-checked and agreed on 22/22 probe cases.

**Correction applied once**, judging each article at its own original publication time:

| | before | dup | not actionable | out of scope / review | after | id | revision |
| --- | --- | --- | --- | --- | --- | --- | --- |
| WEEKLY | 83 | 1 | 15 | 46 / 6 | **15** (9+6) | `3a9278b5` unchanged | 2 → 3 |
| INITIAL_BASELINE | 123 | 0 | 30 | 43 / 3 | **47** (34+13) | `954bd243` unchanged | 1 → 2 |

First `published_at` (2026-09-15T08:35:11Z), the 09.08~09.14 window and snapshot date 2026-09-15
are preserved. 289 programs and 433 versions remain stored; the TECHFEST pair keeps both
`program_sources` rows. `weekly_announcements` is still empty — the correction sent nothing.
Recovery snapshot: `admin_audit` `PRE_CORRECTION_RECOVERY_SNAPSHOT`, id
`93db0b0f-e454-4783-99ff-4fbeb0ff1bd3`.

**Calibration.** Reviewed ≥10 samples per class before writing. Two rule defects were found and
fixed rather than tuning counts: English investor-programme titles ("INVESTOR DAY") were missed,
and incumbent-manufacturer upgrades (제조 DX, 부품 국산화, 책임보험료) reached CONDITIONAL through
an incidental 실증/사업화 mention.

**Web.** `WeeklyBriefingPage.jsx` renders two sections with the inline restriction and falls back
to a flat list for pre-v1.1 articles; `NoticePage.jsx` shows `새로 확인 N건 · 변경 M건`. The GFC
`tests/fixtures/radar-migrations/` copy was refreshed (it had been missing the baseline migration).

## 18. Open questions for the operator

1. **Is `vars.RADAR_V2_ENABLED` actually `true`?** Not inspectable without `gh` (the GitHub CLI
   is not installed on this machine). The 2026-09-15 run published at 08:35 UTC, 2 h 35 m after
   the 06:00 UTC cron — consistent with a manual `workflow_dispatch` rather than a schedule.
   **Whether the next Tuesday run fires automatically is unconfirmed.**
2. **Is `vars.RADAR_V2_DELIVERY_ENABLED` set?** Zero announcements exist, but both subscriptions
   are currently non-deliverable, so delivery has never actually been exercised end to end.
3. **Should "신규" be re-worded** to say *newly found by StartupRadar* rather than *newly
   announced*, or should NEW be redefined against official publication dates? The latter is only
   partially possible — a reliable official publication date exists for BizInfo (`creatPnttm`)
   but **not** for K-Startup or the direct HTML channels.
4. **What is the intended relevance policy boundary?** e.g. are 청년/소상공인 programs open to
   student founders in scope? Is an internship posting always out? Needed before building a
   filter.
5. **Should the local startup-radar checkout be fast-forwarded** to `origin/main` and the
   `codex/production-hardening-20260914` branch deleted?
6. **83 NEW items in one weekly issue** is large for a curated digest. Is there a target volume
   (e.g. top 10–20 after relevance filtering)?
7. Should the stale `ARCHITECTURE.md` / `PRODUCTION-OPERATIONS.md` status paragraphs be
   corrected, or explicitly marked historical?
