# Phase A: Python HTTP dependency audit

The controlling requirement is [GFC-OPERATING-GOAL.md](GFC-OPERATING-GOAL.md), received 2026-09-12. It supersedes earlier documents that called a Python API host a mandatory prerequisite. Preserve the existing engine and GFC UI. No new host is selected or needed to continue Phase A.

## Current checkpoint

**Phase A is in progress; the final A/B/C Python server decision is not yet proven.** Four member read paths now use narrow Supabase RPCs: membership/team context, own-team profile, stored program feed and program detail. Deterministic Python batch refresh prepares five presets and current team results, including historical program versions. Profile mutation, preferences and health remain conversion work. A residual Python call in the current code is an implementation task, not proof that Python hosting is necessary.

`public.gfc_radar_me()` executes as the caller, checks `auth.uid()` and existing GFC `public.my_role()`, and reads existing team RLS policies. It exposes only the caller's teams, their profiles/version and the GFC admin flag. It does not return Telegram IDs or admin internals. No new table grants or RLS relaxation are needed. `startup_radar` remains outside the exposed Data API schemas. Authenticated callers have EXECUTE on this one function; PUBLIC and anon do not. This follows [Supabase function security](https://supabase.com/docs/guides/database/functions) and [API access guidance](https://supabase.com/docs/guides/api/securing-your-api).

## Every current HTTP endpoint

Classification describes the appropriate final mechanism; it does not claim every conversion is complete. A = safe database access, B = privileged worker operation, C = immediate action with a justified response-time requirement. Existing Python routes stay available for compatibility and tests during conversion.

| Method and route | Current caller / responsibility | Group and migration decision |
|---|---|---|
| GET `/` | Legacy engine root | Utility only. GFC is the member UI; no production Python hosting requirement |
| GET `/static/app.js`, mounted `/static/*` | Disabled legacy dashboard | Preserve disabled utility; no member dependency |
| GET `/openapi.json` | FastAPI-generated schema metadata | Utility only; no GFC member caller or production hosting requirement |
| GET `/api/public-config` | Legacy dashboard configuration | A: GFC already owns Supabase configuration and preset labels; do not introduce a second login |
| GET `/api/me` | GFC feed, detail, settings; team selector | A: **converted** to `gfc_radar_me` RPC + RLS |
| GET `/api/teams/{team_id}/profile` | GFC settings | A: **converted** through same scoped RPC; inaccessible team rejected |
| GET `/api/programs` | GFC member feed, filters and pagination | A: **converted** to `gfc_radar_programs` + RLS/SQL filters. B: `REFRESH` batch computes presets/team results. Missing/stale calculation is explicit pending |
| GET `/api/programs/{program_id}` | GFC detail, evidence and historical versions | A: **converted** to `gfc_radar_program_detail`, safe facts/documents/history and persisted evaluation. Exact program/profile versions must agree; stale eligibility remains null |
| POST `/api/teams` | GFC first/multiple profile creation | C: transactional DB team + owner + preset/version creation, then async calculation. Must not trust a submitted owner ID or copy admin authority |
| PATCH `/api/teams/{team_id}/profile` | GFC progressive settings | C: validated atomic version-checked update, immutable history, async recalculation request; preserve explicit fields and UNKNOWN |
| GET `/api/teams/{team_id}/preferences` | GFC settings | A: stored preferences and a safe channel-connection indicator; no chat ID exposure |
| PUT `/api/teams/{team_id}/preferences` | GFC settings | A: owner/editor write. Batch delivery must read current preferences before planning and sending; avoid a secret-dependent synchronous fanout |
| GET `/api/teams/{team_id}/history` | Legacy member utility | A: narrow projection of own-team delivery history; omit transport identifiers/payloads |
| GET `/api/admin/health` | GFC admin health | A: GFC-admin-only safe projection of source/run counts and errors; existing admin_users-only policies need review before direct reads |
| GET `/api/admin/failures` | Legacy admin utility | A: admin-only source/document failure projection |
| GET `/api/admin/duplicates` | Legacy admin utility | A: admin-only possible duplicate list |
| PATCH `/api/admin/duplicates/{duplicate_id}` | Legacy review utility | A: audited DB state decision; no silent canonical/history merge |
| POST `/api/admin/jobs` | Legacy web utility, shared dispatch service | B: persist authorized batch request; worker consumes. GitHub dispatch token must stay in a trusted runtime |
| POST `/api/admin/jobs/{job_id}/cancel` | Legacy admin utility | A: audited DB cancellation rules; preserve current race/terminal-state guards |
| PUT `/api/admin/scheduling` | Legacy admin utility | A: audited DB configuration. Keep disabled until live validation |
| GET `/api/admin/teams` | Legacy admin utility | A: admin list of team identity only; no unscoped private profile dump |
| POST `/api/admin/teams` | Legacy admin utility | C: authorized transactional DB team creation with audit |
| POST `/api/admin/teams/{team_id}/members` | Legacy admin utility | C: authorized membership mutation, no GFC role escalation |
| GET `/api/admin/notifications` | Legacy admin utility | A: admin-only safe delivery state projection |
| POST `/api/admin/notifications/{batch_id}/recover` | Legacy admin utility | B: audited recovery action consumed by worker; uncertain sends never blindly retried |
| PUT `/api/admin/subscriptions` | Legacy admin utility | C: privileged channel mapping/configuration. No bot token needed for a DB mapping; an actual test send belongs to B |
| GET `/api/admin/trace/{recommendation_id}` | Legacy admin utility | A: authorized persisted provenance/evaluation/profile trace, retaining additional team privacy check |
| POST `/telegram/webhook` | Optional V2 inbound Telegram commands | B: secret-dependent trusted receiver. Existing V1 Worker remains during coexistence; optional V2 commands do not require a member-facing Python service. Notification-only batch sends require no incoming webhook |

All GFC Radar calls are centralized in `src/lib/noticeApi.js`. The current requested routes are `/api/me`, `/api/programs`, `/api/programs/{id}`, POST `/api/teams`, GET/PATCH profiles, GET/PUT preferences and GET health. Manual notice CRUD already uses Supabase directly. `radarContext.js` and `radarPrograms.js` convert all four read categories before consulting `VITE_RADAR_API_URL`; there is no permissive HTTP fallback on an RPC denial.

## Immediate recalculation alternatives, in the required order

1. **DB deterministic engine:** possible, but duplicating the existing Python evidence/date/eligibility/ranking logic in PL/pgSQL would add semantic drift. Simple authorization/profile validation belongs in DB; do not port the entire engine merely to hide latency.
2. **Async job/outbox:** preferred candidate. Save profile/version and enqueue a deduplicated request atomically; Python worker reuses the existing engine. Reads show explicit pending until matching profile/program/engine results exist. Batch precomputes all five presets so Stage 0 can browse immediately without a team or optional data. Pending is not NEEDS_INFO or UNVERIFIABLE.
3. **GitHub Actions dispatch:** can shorten queue latency but needs a trusted token-bearing trigger; browser must never hold the token. Scheduled/manual worker polling remains viable. Existing enable and delivery gates must remain intact during validation.
4. **Edge Function:** evaluate only if measured/required queue responsiveness cannot be met otherwise, or a secure dispatch receiver is needed. It must keep JWT/member/admin checks and secret scope; no broad service-role database proxy.
5. **Python HTTP:** preserved utility; no endpoint has yet demonstrated that an always-on Python service is structurally necessary. Do not provision one from an old frontend URL assumption.

## Next concrete implementation and evidence

Persisted feed/detail and batch warming are implemented. Next convert profile/preference mutation contracts and add atomic recalculation queue handling, then verify version/concurrency and browser behavior. Current scheduled polling catches profile changes when enabled; there is not yet an atomic profile-job queue. Apply each reviewed migration individually with a fresh shared-GFC inventory. Complete the A/B/C server decision after those contracts are implemented and verified, before considering hosting.

Live source credentials, actual OAuth/role browser tests, designated notification recipients and matched-period V1/V2 comparison remain operating gates. These do not block the direct Supabase refactor. No merge, schedule enable, notification send or V1 cutover is authorized merely by successful CI.

## Stored result contract (2026-09-12)

`20260912134624_gfc_radar_stored_program_reads.sql` is applied individually to the shared project. Two RLS tables hold batch generation/state and presentation results. Only the worker writes them. Two public SECURITY INVOKER RPCs expose member feed/detail; two private invoker helpers retain the same RLS boundary. PUBLIC/anon execution is revoked; authenticated execution is limited to those exact functions. No existing GFC table, policy or Auth identity is modified.

A result is usable only for the exact program version, current raw team profile/version, current Asia/Seoul date and current generation. Generation includes preset defaults, configured ranking weights and engine versions. Missing/stale results return `eligibility:null`, `recommendation:null` and PENDING, or FAILED after a failed refresh. These are computation states, not new eligibility states. Facts and evidence remain readable. SQL checks the live deadline on every read and suppresses closed recommendations even within a cached day.

`python -m radar.cli run --kind REFRESH` reuses the existing deterministic engines without ingestion, AI or Telegram delivery. It warms all five presets and team scopes in version batches of 100, skips unchanged same-day results, and updates failure state with a class name only. Existing ingestion/delivery jobs also refresh the read model. Enabled TICK polls for changed profiles/new dates; repository and DB schedule gates remain disabled during validation. REFRESH is also available as a manual workflow kind under the existing repository enable gate.

Operational limits: no atomic profile-change job exists yet; a concurrent edit stays pending until a subsequent refresh. No hourly latency promise applies while schedules are disabled. Work/storage scale with `(teams + 5) × retained program versions`, with daily recomputation and per-row queries; measure runtime and DB query plans before a large catalog. RPC filtering/pagination executes in DB, but its current materialized candidate query invokes a helper per matching program. It avoids browser catalog downloads and page-load AI, not all linear DB work. Ranking-weight changes are reflected when the next refresh changes generation. Engine changes must update their version tags. Final Python API status remains undecided until the remaining Phase A contracts are verified.
