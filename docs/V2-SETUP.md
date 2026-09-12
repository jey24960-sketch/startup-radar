# V2 setup and migration checkpoint

## Status

V2 remains staging. The user selected the existing GFC project `etvffzxqdgblvkfdikwl`; the isolated `startup_radar` baseline and FK indexes have been applied. Existing GFC objects/data were verified unchanged. GFC branch previews have deployed, but production /notice and Python API integration remain pending. No V1 cutover or Telegram switch has happened. GFC-NOTICE-INTEGRATION-DECISION.md is the latest architecture: existing GFC Google OAuth and React UI, separate Radar API/engine. See GFC-NOTICE-INTEGRATION.md and DEPLOYMENT.md for current contracts and remaining gates.

## Local verification

- Python 3.12 recommended (development verification currently also passes on installed Python 3.11).
- Create a venv, install requirements-v2.lock.txt.
- npm ci
- python -m pytest: core/unit tests; PostgreSQL integration tests require TEST_DATABASE_URL.
- node tests/database.test.mjs: apply migrations to a fresh local PostgreSQL WASM engine and exercise RLS.
- node tools/test_database.mjs: start an ephemeral loopback-only PostgreSQL test server at port 55432.
- Set TEST_DATABASE_URL to postgresql://postgres:postgres@127.0.0.1:55432/postgres?sslmode=disable, then run python -m pytest.
- node --test tests/worker.test.mjs

The PGlite test engine does not emulate Supabase Auth, hosted API settings, production concurrency or deployment. It is strictly a PostgreSQL SQL/repository integration test dependency, not the V2 production database.

## Supabase/PostgreSQL

Use the existing GFC Supabase project `etvffzxqdgblvkfdikwl`. Do not create a new project. All Radar data belongs to `startup_radar`; public.teams/profiles/projects are independent GFC objects. Obtain DATABASE_URL from the selected project's Connect panel, use TLS, and verify a backend identity restricted to the required Radar privileges. The repository disables prepared statements for transaction pooling (prepare_threshold=None). Do not guess pooler hosts.

The baseline creates 28 tables; the GFC membership/cache migration brings startup_radar to 31 tables with RLS. Shared auth.users supplies identity. Existing public.profiles.role member/admin is required for Radar access; Radar team memberships additionally isolate private team data. Web and Telegram administrator checks use public.my_role(), not the legacy admin_users table alone. No users or memberships are created by migration. The former five local-only radar migrations are archived under docs/legacy-migrations and must not be applied to this project.

The backend repository can impersonate an authenticated request only after the application validates the Supabase user identity. It sets a transaction-local authenticated role and auth.uid claim. FastAPI now validates the bearer token with Supabase auth.get_user before setting the transaction-local identity. Never pass an untrusted user_id directly from a browser to Database methods.

No anon access is granted. Team profiles/evaluations/recommendations are membership-scoped; Telegram IDs and internal operational tables are administrator-only. Verified GFC members can create their own Radar team through POST /api/teams, including preset 0 without optional profile data. Cross-user membership management remains an administrator operation. Browser-facing service-role keys are prohibited. Profile versions are append-only for member roles.

## V1 safety bridge

V1 analysis errors now return explicit outcomes. Partial successes can still deliver verified parsed results while the command exits nonzero for incomplete ingestion/analysis. Per-program delivery callbacks record only accepted items, preserving the unsent tail for subsequent runs. CLI help no longer requires secrets. Business dates use Asia/Seoul.

The Worker adds TELEGRAM_WEBHOOK_SECRET and UPDATE_GUARD Durable Object binding. wrangler.toml declares a SQLite-backed TelegramUpdateGuard class. Before deploying this bridge, set the Worker secrets, deploy the binding and configure Telegram setWebhook with the same secret_token. Existing deployed V1 is unchanged until deployment. Updated code fails closed if security configuration is absent.

The update claim is committed before GitHub dispatch. External dispatch and storage cannot form one atomic transaction: ambiguous failures remain UNCERTAIN and require inspecting GitHub before issuing a fresh command. This deliberately prevents automatic double-dispatch but is not exactly-once delivery. Durable claims currently have no retention cleanup.

## Current external/configuration dependencies

- DATABASE_URL: runtime PostgreSQL connection to the selected shared project; still missing locally.
- SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY: authenticated web integration; browser receives only the publishable key.
- KSTARTUP_API_KEY and BIZINFO_API_KEY: official ingestion credentials.
- ANTHROPIC_API_KEY, optional RADAR_EXTRACTION_MODEL: evidence extraction.
- TELEGRAM_BOT_TOKEN plus team subscriptions: V2 notification delivery.
- TELEGRAM_WEBHOOK_SECRET and UPDATE_GUARD: V1 webhook safety bridge.
- A configured search provider and optional Playwright Chromium: additional discovery capabilities.

No production messages were sent. V2 API/dashboard, initial registry, scheduler, runtime commands and batch delivery are implemented locally. Hosted setup, full long-tail expansion, production concurrency/recovery validation, live parallel comparison and cutover remain pending.


## Runtime migration and web build

The following reviewed migrations have been applied to the shared project:

- `20260912114449_startup_radar_shared_gfc_staging.sql`
- `20260912114958_startup_radar_fk_indexes.sql`
- `20260912123752_gfc_member_access_and_feed_cache.sql`

The GFC repository owns the separately applied `20260912123813_gfc_manual_notices.sql`. It creates public.gfc_notices without copying Radar programs. These entries coexist in the shared migration ledger.

The baseline folds the complete former five-migration model into additive DDL, including snapshots, authoritative publisher identity, job cancellation and delivery batches. The follow-up supplies 16 FK indexes. Both use transactions and short lock timeouts. The shared migration ledger contains GFC entries owned by another repository: never bulk-push or repair that history from this repository. Future reviewed migrations must be applied individually after a fresh shared-object inventory. Never run test reset fixtures on the hosted project. Existing JSON delivery history has not been imported.

```bash
python -m venv .venv
# Activate the venv with the command appropriate to your shell.
pip install -r requirements-v2.lock.txt
npm ci
npm run build
python -m radar.cli seed-sources
uvicorn radar.web:app --host 127.0.0.1 --port 8000
```

Set process environment variables first; `.env.example` documents names but `.env` is not automatically loaded. A production host needs HTTPS, a process manager, restricted database credentials, outbound HTTPS, the built static assets and writable temporary space for document parsing. Host choice is not yet selected. The backend runs Python; the frontend alone is not a complete deployment.

## Auth and membership setup

Preserve the shared GFC Auth signup/providers/site URL/settings. Do not disable signup or replace its redirect configuration for Radar. Existing GFC accounts are the identity source. Use the existing GFC membership process to verify public.profiles.role. Radar team membership never grants GFC membership or admin status. No separate Radar identity or login is required. If staging eventually needs an extra redirect URL, add the precise URL while retaining existing GFC entries. A backend operator can bootstrap a team for an explicitly designated existing GFC member. This command does not grant GFC membership or GFC administrator rights:

```bash
python -m radar.cli bootstrap-team --user-id EXISTING_AUTH_UUID --name GFC
```

This creates preset-0 membership, a profile and immutable profile version. Never derive administrator status from user-editable metadata. Further teams/members are managed through authenticated admin endpoints (`POST /api/admin/teams`, `POST /api/admin/teams/{id}/members`). The application currently supplies APIs, not a complete in-app invitation management screen. Invitation email remains a Supabase administrative operation. Production member login uses the existing GFC Google OAuth session. GFC sends its access token in the Radar API Authorization header. The preserved, disabled legacy dashboard has an OTP flow for separate utility testing; it is not the member onboarding path.

`startup_radar` is not added to the public Data API schemas: the backend uses direct PostgreSQL. RLS remains enabled. Configure a restricted backend DB identity and verify role switching through the selected pooler. Hosted role/claim SQL tests passed, but real browser JWT login and backend/pooler connections remain pending. Separate origins do not automatically share a browser session merely because they use the same Supabase project; see WEB-INTEGRATION.md.

## V2 Telegram

V2 webhook endpoint is `POST /telegram/webhook` on the HTTPS backend. It checks `X-Telegram-Bot-Api-Secret-Token` against `TELEGRAM_WEBHOOK_SECRET`. Register Telegram's webhook with that matching `secret_token` through a secure POST; keep bot tokens out of shared links and browser history. Telegram permits one webhook per bot. Use a separate test bot during parallel validation; switching the existing bot would replace the V1 command path.

Map an authorized Telegram sender to an application administrator in `startup_radar.telegram_admins`. `/id` returns the sender/chat identifiers; other commands require this mapping and the linked user's existing GFC admin role, checked through `public.my_role()`. Create a `telegram_subscriptions` record through `PUT /api/admin/subscriptions`; V2 does not read the single V1 TELEGRAM_CHAT_ID for delivery. Commands: `/run`, `/digest`, `/status`, `/health`, `/sources`, `/team`, `/stage`, `/stop`, `/help`, `/id`. `/stop` changes PostgreSQL scheduling state and does not interrupt already running/manual jobs.

`/run` and dashboard requests need RADAR_GITHUB_TOKEN (repository Actions write permission), GITHUB_REPOSITORY, and RADAR_GITHUB_REF. The workflow must exist at that ref. Request IDs are persisted before dispatch; missing credentials/rejection/uncertainty appear in job history. A GitHub HTTP 204 means accepted for dispatch, not completed execution.

The V1 Worker safety bridge is a different deployment path and retains its Durable Object binding. Do not point Telegram to both backends or enable polling concurrently.

## GitHub Actions V2 cadence

`.github/workflows/startup_radar_v2.yml` wakes hourly at minute 17. Business schedules live in PostgreSQL, not separate cron constants: default daily ingestion 06:00 Seoul, weekly Tuesday digest after 15:00, daily deadline review after 15:00. Claims allow one scheduled run per logical period and tolerate delayed same-day wake-ups. GitHub scheduling is not an exact-time guarantee.

Repository variables:

- `RADAR_V2_ENABLED=true`: enable the V2 workflow. Default absent means disabled.
- `RADAR_V2_DELIVERY_ENABLED=true`: permit real Telegram sends. Default absent means no notifications are planned or sent; recommendations can still be computed.

Workflow secrets: `RADAR_DATABASE_URL` (mapped to DATABASE_URL), ANTHROPIC_API_KEY, KSTARTUP_API_KEY, BIZINFO_API_KEY and TELEGRAM_BOT_TOKEN. The workflow group serializes V2 runs; a PostgreSQL advisory lock serializes direct CLI runs. Notification batch locks and unique keys add separate duplicate protection.

```bash
python -m radar.cli run --kind INGEST --source korea-startup-html
python -m radar.cli run --kind DIGEST
# Only when an actual test/production send is intended:
python -m radar.cli run --kind DIGEST --deliver
```

Without `--deliver`, delivery tasks refresh recommendations without reserving the notification ledger. Manual CLI requests bypass cadence. Failed/partial work returns nonzero to Actions. Failed/uncertain schedule claims do not retry blindly; inspect job/source errors and issue a deliberate manual run. Stale job handling and automated operator alerts need further operational validation.

## Local dashboard preview

Start `node tools/test_database.mjs`, set TEST_DATABASE_URL to its loopback URL, then run `python -m tools.preview`. It requires the ephemeral test marker, resets only that explicit fixture database, binds `127.0.0.1:8765`, seeds labeled fictional programs, and injects a fixture user outside the production entry point. External dispatch/webhook actions are blocked. Never deploy this module. Stop it before running integration tests against the same fixture database.

## Native PostgreSQL test suite

For real lock/concurrency tests, create an empty local PostgreSQL database named `radar_test`. Set `TEST_DATABASE_URL` to its loopback connection and `TEST_NATIVE_POSTGRES=1`, then run `python -m tools.bootstrap_test_postgres` once and `python -m pytest -q`. Bootstrap refuses hosted targets, another database name or existing auth/radar schemas. The tests require the explicit ephemeral marker and reset fixture data. Auth users are mocked; this does not validate hosted Supabase Auth.

`.github/workflows/test_v2.yml` provisions PostgreSQL 17 for pull requests/manual verification, bootstraps all migrations, runs Python/native concurrency tests, PGlite RLS assertions, Worker tests and the frontend build. Locally, the native concurrency suite was exercised against PostgreSQL 18.4; the GitHub job has passed remotely, including PostgreSQL integration and native concurrency checks (run 34695302768, Python 151 passed).

## V1/V2 parallel comparison

V1 run reports now include `all_programs` before previously-sent filtering, analysis status, collection timestamp and failures. Keep the V1 and V2 collections close in time and use a separate test bot if delivery is exercised. With the V1 report available:

```bash
python -m radar.cli compare --v1 path/to/v1-report.json --team-id EXISTING_TEAM_UUID --output path/to/comparison.json
```

The command only reads V2 data, evaluates its current program/profile snapshot, and writes a local report. It does not send notifications or approve cutover. It lists exact URL/alias matches, unique title+organization matches, V1-only/V2-only items, ambiguous/fuzzy candidates, eligibility review, source failures and profile version. Missing collection timestamps, old filtered V1 reports and collection gaps over six hours are explicit limitations. The V2 catalog may include closed or older notices; raw count differences are not coverage measurements. Run a matched-period cohort repeatedly and investigate each difference before any production switch. No live matched-period V1/V2 comparison has been completed yet.

See [OPERATIONS.md](OPERATIONS.md) for source failures, dispatch races, audited request cancellation, Telegram recovery and duplicate review.


## Extraction schema update

Requirements schema 2.0.2 accepts explicit `application_start_at`/`application_end_at` ISO timestamps with timezone and a full verbatim `date_evidence_quote`. Date-only fields remain supported when the source does not specify a time. `benefit_evidence_quote` is needed to retain an AI-generated benefit summary. Unsupported OR/exceptions yield uncertain AI requirements. Existing official Program data is unchanged when extraction fails. Re-ingest source records to benefit from the new validation; it does not retroactively certify earlier AI outputs.


Official API dates carry DATE precision in extraction 2.0.3. A matching original notice can add a same-day time and produce DATETIME; it cannot change the API calendar day. Existing records with UNKNOWN precision require re-ingestion to classify their granularity. The web detail marks times requiring original-source confirmation. No new environment variable or migration is needed for this normalized schema change.

Before declaring the project complete, follow the external gates in [COMPLETION-AUDIT.md](COMPLETION-AUDIT.md).

Portable Docker packaging and an offline configuration checker are now available. See [DEPLOYMENT.md](DEPLOYMENT.md). `python -m radar.deployment --serve` checks web inputs and starts the production application on the host's PORT. Container build/import/asset verification passed remotely in run 34695302768; this workstation has no Docker/Podman runtime. The container has not yet been connected to a hosted API runtime and the real shared DB.
