# GFC Weekly Briefing

This supersedes the production-hardening completion priorities on 2026-09-14.
Normal production is official APIs -> one weekly publication -> one Telegram announcement.
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
Only an explicit `--revision-note` revises the current issue. Prior item snapshots and version links
remain in `admin_audit`, the briefing ID/first publication time remain stable, and announcement uniqueness
does not reset. This is for verified corrections, never a blanket scheduled retry.

Weeks are Monday-Sunday in Seoul, with exact dates shown in the title/article.
The first briefing includes currently obtained opportunities; later issues compare each opportunity
against its latest previously published snapshot, not just the immediately preceding (possibly empty) issue.
Only material changes reappear. Already closed opportunities are excluded.

## Data and Safety

`weekly_briefings` and `weekly_briefing_items` are separate from manual `public.gfc_notices`.
Existing program/source/version identities and provenance remain authoritative. Exact canonical URL,
publisher identity and existing deterministic identity matching deduplicate records; fuzzy candidates are not merged.
Items retain a version FK and immutable editorial snapshot. Snapshot comparison includes official attachment
URLs when advertised, not unverified content hashes. An unchanged URL with silently replaced bytes cannot be
detected without fetching the binary; full attachment processing is deferred.

Weekly acquisition uses existing official API discovery/pagination/normalization, not portal scraping,
AI, OCR, eligibility, ranking or team refresh. Program facts can be incomplete without blocking a post.
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
with no rejected identities, failed records, stalled pagination or other errors. Both sources must
meet that contract for a green execution. Raw source/ingestion `PARTIAL_SUCCESS`, advertised counts,
`pagination_complete=false` and `coverage_warning=BOUNDED_WEEKLY_SCOPE` remain visible in the run.
Weekly query completion never advances the source's full-scan timestamp; an API-advertised count
is labeled `BOUNDED_WEEKLY_QUERY`, not a nationwide or historical denominator.
Authentication, HTTP, network, JSON/schema and persistence failures never receive this exception.
Historical published one-page samples (including the initial 20-row window) may be recognized on
ordinary no-write reruns using the same strict persisted evidence, with
`coverage_warning=PUBLISHED_BOUNDED_COLLECTION`; their stored status and content remain unchanged.

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
