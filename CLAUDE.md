# CLAUDE.md — StartupRadar (worker/backend)

## What this is

**GFC (Global Founders Club)** is a university-student-led, global, non-profit startup
association with no separate legal personality. It is **not** affiliated with one university
and is **unrelated to Global Founders Capital**. Principles: Global from Day 1, Execution over
Talk, Problem First, Data over Opinion, AI-Native Building.

**StartupRadar** gives GFC founders *one curated weekly set of actionable startup
opportunities*. Typical reader: university-student founder, aspiring/pre-business founder,
early team, early-stage startup.

StartupRadar is **not** a general Korean SME subsidy search engine, a merchant-support portal,
an employment/internship board, or a complete national business-support archive.
**Collection may be broad; publication must be selective.**

## Repositories

| Repo | Role |
| --- | --- |
| `jey24960-sketch/startup-radar` (this repo) | Python worker, GitHub Actions batch, Supabase migrations |
| `jey24960-sketch/GFC-startup.com` | React/Vite member web on Vercel (`/notice`, `/notice/weekly/:id`) |

Shared Supabase project `etvffzxqdgblvkfdikwl`, private schema `startup_radar`.

## Authoritative documents

Current source of truth, in this order:

1. **`docs/WEEKLY-BRIEFING.md`** — the production weekly contract. It explicitly supersedes
   `docs/PRODUCTION-HARDENING.md`.
2. `docs/CLAUDE-HANDOFF.md` — audited current-state detail (this takeover).
3. `README.md`, `docs/SOURCES.md` (API contracts), `docs/DEPLOYMENT.md`,
   `weekly-direct-sources.json`, `.github/workflows/startup_radar_v2.yml`.

**Historical / not current runbooks:** `PRODUCTION-HARDENING.md` (self-labelled IN PROGRESS),
`V1-AUDIT.md`, `V2-SPEC.md`, `V2-PROGRESS.md`, `LEGACY-V1-README.md`, `COMPLETION-AUDIT.md`,
`GFC-OPERATING-GOAL.md`, `GFC-NOTICE-INTEGRATION*.md`.
**Known stale:** `docs/ARCHITECTURE.md` ("V2 schedules remain disabled" — false, production has
published) and `docs/PRODUCTION-OPERATIONS.md` (describes the retired hourly `17 * * * *` TICK
and "화요일 15:17"; the real schedule is `0 6 * * 2`). Trust `WEEKLY-BRIEFING.md` over both.

There is **no `AGENTS.md` in either repository** as of 2026-09-16. If one appears later, read it
first and treat its repository instructions as binding.

## Weekly product invariants — do not break

- **One** publication per operational Seoul week (Mon–Sun), **one** Telegram announcement — posted to
  the ONE official GFC channel (`runtime_settings.weekly_telegram_channel`), never to per-team
  subscriptions. Members join the channel once; no ID/chat-ID submission, no operator binding.
  Schedule: `cron: '0 6 * * 2'` = Tuesday 15:00 Asia/Seoul, gated by `vars.RADAR_V2_ENABLED`.
- A published week is **stable**: reruns return the existing ID and do not rewrite it. Only an
  explicit `--revision-note` revises, preserving ID, first `published_at`, and prior-item audit.
- The weekly path uses **no AI, no OCR, no eligibility engine, no recommendations, no team
  refresh** (`ingest(..., structured_only=True)`).
- All-source failure **never** publishes an empty issue or announces. Partial success may
  publish real items and keeps a nonzero CLI exit.
- Exactly **one** `INITIAL_BASELINE` article may exist (unique index). It establishes known
  history and **cannot** send Telegram (`weekly.py` `announce()` returns `BASELINE_ARCHIVE`).
  An unconfigured channel is `NO_BROADCAST_CHANNEL`, a valid no-op, never a publication failure.
- Weekly/baseline rows are member-only via SECURITY INVOKER RPCs
  (`gfc_radar_weekly_briefings`, `gfc_radar_weekly_briefing`) + `public.my_role()` in
  `('member','admin')`. Preserve GFC Auth/RLS; never grant client writes.
- **Never infer unknown dates or eligibility.** Unknown stays unknown; the member view says
  "공식 공고 확인 필요". A year is never inferred from today's clock. Crawler/DB timestamps are
  **not** official publication dates.
- **Auditability:** revisions and the baseline split write `admin_audit`; never erase history,
  never delete older evidence/versions.
- **No fuzzy dedup merges.** Identity is deterministic only (publisher ID → exact canonical URL
  + exact title/org → exact full application period with a direct channel on one side).

## Scope discipline

- Do **not** merge StartupRadar PR #9 or GFC PR #11 wholesale (both are
  `feat/weekly-admin-controls`). Do not reintroduce daily discovery, `/opportunities`,
  15-minute polling, institution administration tables/UI, or broad member submission
  workflows unless explicitly instructed. Selective reuse of adapters/date parsing is already
  done and is the accepted pattern.
- Do not broaden collection scope, add sources, or enable DEFERRED channels without explicit
  instruction. Bounded one-page collection is a *declared* boundary, not a bug.

## Publication filters (added 2026-09-16, GFC Relevance v1.1)

Collection stays broad; publication is selective. Order: cross-source dedup -> material
NEW/UPDATE -> actionability -> GFC relevance. None of it deletes or edits stored facts.

- **Actionability** (`radar/actionability.py`): `MINIMUM_APPLICATION_LEAD_TIME = 48h`, judged
  against the publication reference time. Withholds CLOSED, NEAR_DEADLINE, UPCOMING, and
  DEADLINE_UNKNOWN unless `deadline_type` is a trusted `ROLLING`/`UNTIL_BUDGET_EXHAUSTED`.
- **Relevance** (`radar/relevance.py`, `gfc-v1.1`): deterministic rules, no AI. HIGH+BROAD →
  `GFC_RELEVANT`, HIGH+RESTRICTED → `CONDITIONAL`, LOW → `OUT_OF_SCOPE`, conflicting/thin →
  `REVIEW_REQUIRED`. Only the first two are ever published. Audience words are never evidence.
- **Storage**: `startup_radar.program_relevance` keyed by `(program_version_id,
  relevance_version)` — **never add relevance to `weekly.MATERIAL`**, it drives NEW/UPDATE hashes.
- **Dedup** (`identity.cross_source_key`): identical normalized title ≥20 chars **and** identical
  application start **and** end. Organization is intentionally not compared. Still no fuzzy merge.
- **Wording**: member-facing NEW is `새로 확인` (StartupRadar saw it first), never `신규`.

`tools/export_relevance_sql.py` generates the SQL mirror used for backfilling already-stored
versions; `tests/test_relevance_sql_mirror.py` fails if it drifts. Regenerate, never hand-edit.

The 2026-09-15 articles were corrected once in place on 2026-09-16 (WEEKLY 83→15, baseline
123→47), preserving IDs, first `published_at` and windows. See `docs/CLAUDE-HANDOFF.md`.

## Before you start

`git fetch && git status` first. The local checkout has previously been found behind
`origin/main`. `origin/main` is production.

Local environment note (verified 2026-09-16): this machine blocks `libpq`, so `psycopg` cannot
load and every database-backed Python test fails at import. Pure-logic tests
(`test_actionability`, `test_relevance`, `test_cross_source_dedup`, `test_relevance_sql_mirror`)
run fine. Three `test_weekly_scope` failures are pre-existing and caused by the same block.
