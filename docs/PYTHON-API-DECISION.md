# Phase A: Python HTTP dependency audit

The controlling requirement is [GFC-OPERATING-GOAL.md](GFC-OPERATING-GOAL.md), received 2026-09-12. It supersedes earlier documents that called a Python API host a mandatory prerequisite. Preserve the existing engine and GFC UI. No new host is selected or needed to continue Phase A.

## Current checkpoint

**Phase A complete — A. NOT REQUIRED.** All nine necessary GFC member/admin request paths now use Supabase RPC. Manual notices already use Supabase directly. Python batch workers retain ingestion, document parsing, analysis, deterministic eligibility/recommendations and notifications. No remaining required frontend operation needs a hosted Python HTTP endpoint. This is the architecture decision, not a claim that real operating acceptance has passed.

`public.gfc_radar_me()` executes as the caller, checks `auth.uid()` and existing GFC `public.my_role()`, and reads existing team RLS policies. It exposes only the caller's teams, their profiles/version and the GFC admin flag. It does not return Telegram IDs or admin internals. No new table grants or RLS relaxation are needed. `startup_radar` remains outside the exposed Data API schemas. Authenticated callers have EXECUTE on this one function; PUBLIC and anon do not. This follows [Supabase function security](https://supabase.com/docs/guides/database/functions) and [API access guidance](https://supabase.com/docs/guides/api/securing-your-api).

## Every current HTTP endpoint

All required GFC calls are converted. Legacy utility rows classify possible mechanisms; they are preserved optional tools, not newly implemented GFC RPCs or required production HTTP services. A = safe database access, B = privileged worker operation, C = immediate action with a justified response-time requirement. Existing Python routes stay available for compatibility and tests during conversion.

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
| POST `/api/teams` | GFC first/multiple profile creation | C: **converted** to idempotent gfc_radar_create_team; authenticated actor owns the new team. Profile/history/calculation request are atomic |
| PATCH `/api/teams/{team_id}/profile` | GFC progressive settings | C: **converted** to gfc_radar_update_profile, CAS/row lock + existing RLS, immutable history and async calculation request; preserves explicit fields and UNKNOWN |
| GET `/api/teams/{team_id}/preferences` | GFC settings | A: **converted** to gfc_radar_preferences; own-team safe flags/connection indicator, no chat ID |
| PUT `/api/teams/{team_id}/preferences` | GFC settings | A: **converted** to gfc_radar_save_preferences; OWNER/EDITOR, atomic preferences/channel flags/audit. Worker rechecks current preferences at planning and send claim |
| GET `/api/teams/{team_id}/history` | Legacy member utility | A: narrow projection of own-team delivery history; omit transport identifiers/payloads |
| GET `/api/admin/health` | GFC admin health | A: **converted** to gfc_radar_health; GFC admin authorization independent of legacy Radar admin mapping, safe source/run/failure/calculation/queue projection |
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

All GFC Radar calls are centralized in `src/lib/noticeApi.js`. Its context, programs, profile-command and settings modules map the nine requested paths to eight RPC functions (context and profile reads share gfc_radar_me). Manual notice CRUD uses Supabase directly. The Python HTTP fallback and VITE_RADAR_API_URL lookup are removed. Unknown routes fail explicitly; RPC denials cannot fall back to another transport.

## Immediate recalculation alternatives, in the required order

1. **DB deterministic engine:** possible, but duplicating the existing Python evidence/date/eligibility/ranking logic in PL/pgSQL would add semantic drift. Simple authorization/profile validation belongs in DB; do not port the entire engine merely to hide latency.
2. **Async job/outbox:** implemented choice. Save profile/version and enqueue a deduplicated request atomically; Python worker reuses the existing engine. Reads show explicit pending until matching profile/program/engine results exist. Batch precomputes all five presets so Stage 0 can browse immediately without a team or optional data. Pending is not NEEDS_INFO or UNVERIFIABLE.
3. **GitHub Actions dispatch:** can shorten queue latency but needs a trusted token-bearing trigger; browser must never hold the token. Scheduled/manual worker polling remains viable. Existing enable and delivery gates must remain intact during validation.
4. **Edge Function:** evaluate only if measured/required queue responsiveness cannot be met otherwise, or a secure dispatch receiver is needed. It must keep JWT/member/admin checks and secret scope; no broad service-role database proxy.
5. **Python HTTP:** preserved utility; no endpoint has yet demonstrated that an always-on Python service is structurally necessary. Do not provision one from an old frontend URL assumption.

## Phase A evidence and next operating gate

Persisted reads, batch warming, atomic profile commands, preferences and admin health are implemented and verified. Local validation: 166 Python, 65 Node/PGlite and 15 browser tests, all browser tests with no Python origin; Vite build passes. The final settings migration passed 11 grouped rollback-only checks on the actual shared DB; its 1,085 existing GFC/Auth/Storage metadata objects were unchanged, with only three public wrappers added. All three new RPCs reject anonymous REST with HTTP 401. See [settings contract](SETTINGS-HEALTH.md) and GFC-RADAR-SETTINGS-VERIFICATION.json. Next: connect available batch credentials and validate real source/account/data/notification/parallel operation.

Live source credentials, actual OAuth/role browser tests, designated notification recipients and matched-period V1/V2 comparison remain operating gates. These do not block the direct Supabase refactor. No merge, schedule enable, notification send or V1 cutover is authorized merely by successful CI.

## Stored result contract (2026-09-12)

`20260912134624_gfc_radar_stored_program_reads.sql` is applied individually to the shared project. Two RLS tables hold batch generation/state and presentation results. Only the worker writes them. Two public SECURITY INVOKER RPCs expose member feed/detail; two private invoker helpers retain the same RLS boundary. PUBLIC/anon execution is revoked; authenticated execution is limited to those exact functions. No existing GFC table, policy or Auth identity is modified.

A result is usable only for the exact program version, current raw team profile/version, current Asia/Seoul date and current generation. Generation includes preset defaults, configured ranking weights and engine versions. Missing/stale results return `eligibility:null`, `recommendation:null` and PENDING, or FAILED after a failed refresh. These are computation states, not new eligibility states. Facts and evidence remain readable. SQL checks the live deadline on every read and suppresses closed recommendations even within a cached day.

`python -m radar.cli run --kind REFRESH` reuses the existing deterministic engines without ingestion, AI or Telegram delivery. It warms all five presets and team scopes in version batches of 100, skips unchanged same-day results, and updates failure state with a class name only. Existing ingestion/delivery jobs also refresh the read model. Enabled TICK polls for changed profiles/new dates; repository and DB schedule gates remain disabled during validation. REFRESH is also available as a manual workflow kind under the existing repository enable gate.

Operational limits: profile-change requests are now atomic; a concurrent edit stays pending until a subsequent refresh and the old request is superseded. No hourly latency promise applies while schedules are disabled. Work/storage scale with `(teams + 5) × retained program versions`, with daily recomputation and per-row queries; measure runtime and DB query plans before a large catalog. RPC filtering/pagination executes in DB, but its current materialized candidate query invokes a helper per matching program. It avoids browser catalog downloads and page-load AI, not all linear DB work. Ranking-weight changes are reflected when the next refresh changes generation. Engine changes must update their version tags. Final Python API status: A. NOT REQUIRED. Batch runtime credentials and live acceptance remain required.
