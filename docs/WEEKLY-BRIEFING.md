# GFC Weekly Briefing

This supersedes the production-hardening completion priorities on 2026-09-14.
Normal production is official APIs + approved direct official channels -> one weekly publication -> one Telegram announcement.
Personalization, OCR, archives of original binaries and scale benchmarks are deferred, not deleted.

## Schedule and Operations

The sole production calendar is `.github/workflows/startup_radar_v2.yml`:
Tuesday 15:00 Asia/Seoul (06:00 UTC), preserving the existing weekly digest preference.
GitHub may start late; this is not an exact-minute guarantee. `RADAR_V2_ENABLED` gates scheduled execution.
Daily ingestion, high-fit, D-7/D-3 delivery and hourly team recalculation are not on this path.
The prior `scheduling` database value is preserved in the cutover audit, then disabled.

Privileged operator commands, with the existing server credentials:

```text
python -m radar.cli weekly --draft
python -m radar.cli weekly
python -m radar.cli weekly --deliver
python -m radar.cli weekly --check-sources
python -m radar.cli weekly --revision-note "Reason for verified correction"
python -m radar.cli execution-status
```

`--draft` rebuilds only an unpublished current-week draft. The normal command publishes.
A published week is stable: ordinary reruns return its existing ID and do not recollect or rewrite it.
An explicit `--check-sources` (manual workflow input `check_sources`) rechecks and persists official
source observations without modifying an already published issue, its first publication time or audit.
It reports the current check's status separately from `published_collection_status`.
Source checks never send Telegram, even when `--deliver` is also supplied.
Only an explicit `--revision-note` revises the current issue. Prior item snapshots and version links
remain in `admin_audit`, the briefing ID/first publication time remain stable, and announcement uniqueness
does not reset. This is for verified corrections, never a blanket scheduled retry.

Operational week identity remains Monday-Sunday in Seoul. The initial publication can display
the seven completed Seoul calendar days immediately before its original publication date.
Later issues compare each opportunity against its latest published snapshot, including the
one-time initial baseline archive, not just the immediately preceding (possibly empty) issue.
Only material changes reappear. Already closed opportunities are excluded.

### First Publication Correction

Migration `20260915090925_first_publication_baseline.sql` adds an operator-only
`startup_radar.split_initial_publication(briefing_id, reason, expected_count)` function.
It operates only on an existing first published NEW-only snapshot and stored version-linked
source observations. It does not collect sources, edit programs/versions, or call Telegram.

- The recent window is the seven completed Seoul dates before the original publication date.
  A 2026-09-15 publication therefore displays 2026-09-08 through 2026-09-14.
- Official BizInfo `creatPnttm` (portal publication date) takes precedence when present in
  provenance stored by publication time. Otherwise use the normalized official application
  start, only with DATE/DATETIME precision. Missing/invalid dates go to the baseline.
  Crawler observation, insertion and version timestamps never determine official recency.
- Move all other original item rows into one `INITIAL_BASELINE` article, keeping the existing
  deadline order, facts, material hashes and version links. No duplicate live item copies.
- Preserve the weekly ID, operational week and first publication time; increment revision.
  `INITIAL_PUBLICATION_SPLIT` audit records retain the original briefing/items, reason,
  per-program date evidence and both resulting IDs/counts.
- A unique index permits only one initial baseline. Repeating the same correction returns
  its existing result. Other publications or any prior announcement prevent a fresh split.
- Both outputs remain member-only. The baseline uses the same grouped article route with
  an initial-material label and snapshot date, not weekly NEW/UPDATE badges.
- Both outputs establish known program history; the baseline cannot be sent by `announce`.
  Future normal weekly publications retain existing duplicate-protected Telegram behavior.

For this publication-only correction, do not run `weekly --check-sources` or
`weekly --revision-note`: those commands intentionally recollect.

## Data and Safety

`weekly_briefings` and `weekly_briefing_items` are separate from manual `public.gfc_notices`.
Existing program/source/version identities and provenance remain authoritative. Exact canonical URL,
publisher identity and existing deterministic identity matching deduplicate records; fuzzy candidates are not merged.
Items retain a version FK and immutable editorial snapshot. Snapshot comparison includes official attachment
URLs when advertised, not unverified content hashes. An unchanged URL with silently replaced bytes cannot be
detected without fetching the binary; full attachment processing is deferred.

Weekly acquisition uses existing official API discovery/pagination/normalization and approved bounded
official HTML channels. It does not use AI, OCR, eligibility, ranking or team refresh. Program facts can be incomplete without blocking a post.
Unknown fields remain unknown; the Korean member view asks readers to check the official notice.
API-only new versions do not certify eligibility and do not delete older evidence/versions.

Successful acquisition of the defined weekly window may publish a no-new-or-changed-opportunities issue.
All-source failure never publishes an empty issue or sends a publication announcement. Actual partial
source failures may publish valid useful items, retaining `PARTIAL_SUCCESS` and a nonzero CLI exit.
An incomplete empty result does not publish. Previous published posts are never erased by failure.

## Exact Weekly Collection Scope

Policy `GFC_WEEKLY_V1` is applied only in the weekly worker, without changing the source registry:

- K-Startup: the official announcement API with `cond[rcrt_prgs_yn::EQ]=Y` (recruitment in progress),
  `page=1`, `perPage=100`. Existing operator-configured title supplements use the same open filter
  and one 100-row page per title (at most five title queries); repeated publisher IDs are deduplicated.
  The current three supplements are 모두의 창업 프로젝트, SVC Seoul and 베트남 테크페스트.
- BizInfo: its official latest-support-information API with `dataType=json`, `searchCnt=100`,
  `pageUnit=100`, `pageIndex=1`, no category/region restriction. Its documented contract has no
  exact date/change/open filter, so this is the bounded recent official result set, in API order.
- Closed records are excluded from the weekly article using reliable official application end dates.
  Unknown dates/eligibility remain unknown. This window does not guarantee detection of changes to
  older entries outside the returned results, all open programs, or every result matching a title.
  No historical backfill, complete national archive, browser collection, AI, OCR or daily collection.

StartupRadar checks a bounded set of current/recent official opportunities each week.
It is not a complete archive of all historical Korean support programs.
Official contracts: [K-Startup](https://www.data.go.kr/data/15125364/openapi.do)
and [BizInfo](https://www.bizinfo.go.kr/apiDetail.do?id=bizinfoApi), checked 2026-09-15.

Operational success is distinct from full source coverage: a `PAGE_LIMIT` alone is acceptable only
for this explicit one-page window after all obtained unique records have been fetched and persisted,
with no rejected identities, failed records, stalled pagination or other errors. Both backbone sources
and every active direct channel must meet their declared window for a green execution. Raw source/ingestion `PARTIAL_SUCCESS`, advertised counts,
`pagination_complete=false` and `coverage_warning=BOUNDED_WEEKLY_SCOPE` remain visible in the run.
Weekly query completion never advances the source's full-scan timestamp; an API-advertised count
is labeled `BOUNDED_WEEKLY_QUERY`, not a nationwide or historical denominator.
Authentication, HTTP, network, JSON/schema and persistence failures never receive this exception.
Historical published one-page samples (including the initial 20-row window) may be recognized on
ordinary no-write reruns using the same strict persisted evidence, with
`coverage_warning=PUBLISHED_BOUNDED_COLLECTION`; their stored status and content remain unchanged.

## Direct Official Channels

The reviewed registry is `weekly-direct-sources.json`. These eight channels run only as part of the
existing weekly execution. No institution tables, browser dependencies or new member routes were added.
Adapters/date parsing are selectively reused from draft PR #9; the draft itself is not merged.

| Channel | Exact weekly window | Representative validation on 2026-09-15 |
| --- | --- | --- |
| Yonsei startup support | First internal notice page, up to 30 matching Yonsei/CampusTown/student-startup/lab-startup/lecturing recruitment titles; external cross-posts excluded | 3 readable samples; explicit 2026 corporation/address-support period parsed |
| POSTECH startup team | First AIF notice page, only startup-team titles, up to 30 | 3 readable notices; unknown dates held, September 1 deadline closed |
| Gyeonggi CCEI UnicornBridge | Visible desktop homepage program links only, up to 10; hidden archives excluded | 2 readable recruitment pages, both correctly closed |
| KOEF | First official notice page, matching recruitment titles, up to 30 | 3 readable notices; unknown/image timing held, August 28 deadline closed |
| OrangePlanet OrangeFarm | Only the OrangeFarm section of the official program page | Explicit year-round recruitment, not other tracks |
| Antler Korea | Only the official paragraph explicitly accepting individual residency applications year-round | Explicit rolling application; no invented deadline or guaranteed investment |
| Lotte Ventures | Homepage recruitment news links, up to 30 | 3 readable notices; prior cohorts closed or held for unknown timing |
| Asan Nanum Foundation / MARU | First official notice page, startup/MARU recruitment titles only, up to 20 | 3 readable notices; August 28 13:00 batch deadline closed, two uncertain items held |

This is 8 additional channels, not 8 currently open programs. A healthy source can yield zero current
opportunities. Listing scope is one page or one fixed section, not the entire institution or archive.
The configured record cap is a declared scope boundary; `record_cap_reached` retains the limitation.
HTTP/robots/redirect/host checks remain mandatory. Maximum HTML size is 3 MB; details are bounded
to 120,000 characters, with one-second spacing and a 60-request/240-second per-channel budget.
No login, CAPTCHA handling, private APIs or access-restriction workaround is used.
Gyeonggi's separate official program site is corroborated by the
[Gyeonggi government announcement](https://gnews.gg.go.kr/briefing/brief_gongbo_view.do?BS_CODE=s017&number=69742).

Direct records use the same `programs`, `program_versions`, `program_sources` and source snapshots.
Automatic inclusion requires explicit current recruitment with a reliable application period or
explicit rolling acceptance. An event date is not a deadline; a year is never inferred from today's
clock. Short dates inherit only the notice's explicit year or an explicitly dated range.
Closed/upcoming/cancelled/result notices are excluded; uncertain timing or competing application
links go to a small operator review bucket in `source_run_results.coverage.decisions`, with raw evidence
retained in source snapshots. Missing eligibility/support/application-link information does not alone
block a dated recruitment. Member-facing missing values remain "공식 공고 확인 필요".

Canonical notice IDs ignore reviewed pagination/search query keys. Cross-source matching retains the
existing publisher-ID/canonical-URL checks and adds exact organization + title + full application-period
agreement when at least one source is a reviewed direct channel. Conflicting publisher IDs are never
overridden, multiple exact candidates are held, and fuzzy candidates are not automatically merged.

Per-source diagnostics retain name, last attempt/success, status, discovered/persisted/accepted/review/
excluded counts and failure reasons. A direct-source failure remains visible as an honest partial
execution; useful records from other sources may still publish. All-source failure never publishes.

Operator activation and bounded read-only revalidation:

```text
python tools/check_weekly_direct.py --sample 3
python -m radar.cli seed-sources --file weekly-direct-sources.json
python -m radar.cli weekly --check-sources
```

The sample validator has no database writes or announcements. The seed command changes only the named
source settings (eight active; Korea Sejong and Samsung Newsroom explicitly deferred). Normal weekly scheduling and
K-Startup/BizInfo settings are unchanged.

Deferred: Korea University Sejong (local HTML sample succeeded, but GitHub production returned
LIST_PARSE; disabled without a scraping/access workaround); Samsung Newsroom (local sample passed,
but GitHub production robots fetch timed out, so no robots bypass or repeated retries); SNU (public
recruitment pages exist, but published terms restrict reuse without consent).
Other candidates remain deferred based
on PR #9 evidence: Hanyang (public-board adapter/image variability), Bluepoint (browser-only route),
Primer (upcoming cohorts), SparkLabs (introduction/newsletter), FuturePlay/Sopoong/Kakao Ventures
(uncertain current acceptance), restricted CCEI
common boards/U300/dcamp and other difficult channels. These are not enabled by this registry.
Draft StartupRadar PR #9 and GFC PR #11 remain unmerged; daily discovery, institution UI and
`/opportunities` are outside the weekly product.

`gfc_radar_weekly_briefings` and `gfc_radar_weekly_briefing` are SECURITY INVOKER RPCs.
RLS and existing `public.my_role()` require verified GFC member/admin status. A team/profile is unnecessary.
Anonymous and external accounts cannot read these rows; client writes are not granted.
The public RPC excludes private collection IDs, raw errors, chat IDs and extraction internals.

## Telegram

Only a published briefing can produce an announcement. Existing subscription administrative gates,
HEALTHY status and member digest preference must all permit delivery. No subscribers is a valid no-op.
The outbox has a unique briefing/chat key, so one chat cannot receive duplicate posts through multiple teams.
The message contains a title, count, at most three examples and the member-only weekly article URL.
No per-program notification ledger is generated by this flow.

Before sending, a short committed SENDING claim prevents duplicate delivery. FAILED/UNCERTAIN/SENDING
are never automatically resent. Inspect the actual Telegram receipt/owner before any explicit recovery.
An interrupted worker uses the existing verified-dead-owner recovery command. Do not erase its history.

## Web and Validation

`/notice` shows manual GFC notices and weekly Radar issues, including archived weeks.
`/notice/weekly/:id` is the grouped article. Existing advanced browsing is retained at `/radar/programs`;
individual detail/history and team settings remain available but are not on the primary publication path.

Local initial evidence: 45 Python tests passed (weekly and reused ingestion tests), GFC 81 Node/DB tests
passed, production build passed. Existing advanced browser tests were moved to their preserved route.
Production source collection, migration/deployment and live member verification are separate acceptance steps.

## Deferred Checkpoint

Previously implemented incremental-result/session changes are retained with their focused regression tests.
No additional load benchmarks, route splitting, original-binary storage or restore drill is required for
this weekly launch. The older `PRODUCTION-HARDENING.md` is historical progress, not this goal's blocker list.
