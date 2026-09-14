# Production hardening implementation ledger

Status: IN PROGRESS. This is not production acceptance or the current runbook.

Authoritative scope: the user's 2026-09-14 Production Hardening & Reliability Completion Goal, sections 0-72. A verbatim local copy is preserved in the task's startup-radar-hardening/goal-spec.md. Audit baseline: Radar 6ecdf96, GFC 7a369fe.

## Execution sequence

1. Reliability: auditable bounded ingestion retries, no false-green claims, sanitized error causes, complete official pagination.
2. Data quality: explicit reasons and prioritized review, production OCR, measured AI calls and claims outside long transactions, real golden corpus.
3. Product: canonical types, preserved Radar ranking, independently paged mixed sections, evidence and freshness language.
4. Notifications: user preference vs administrative suspension, health, deep links, zero-subscriber correctness.
5. Operations: separate health clocks, queued calculations, operator recovery visibility.
6. Performance: incremental current-version results, measured DB/RPC/100/1,000-team load.
7. Reproducibility: policy-bound private originals and a measured non-production restore.
8. Acceptance: live authorization, actual legacy control-plane state, full regressions, no-delivery production canary and scheduled proof.

## Definition-of-done evidence matrix

Every item remains unproven until current evidence is linked here. Local tests do not alone prove production deployment.

| DoD | Requirement | Current evidence / status |
|---|---|---|
| 1 | No silent healthy state after failed scheduled ingestion | LOCAL PASS: failed empty TICK regression; production PENDING |
| 2 | Safe retry and verified-owner recovery | LOCAL PASS: bounded history and no-delivery recovery; production PENDING |
| 3 | Defined official scope pagination or explicit incompleteness | LOCAL PASS: both adapters, duplicates, short/empty pages, page caps; production scope PENDING |
| 4 | Every current quality state and reason explicit | LOCAL PASS: current-version assessment and review report; live backfill/UI PENDING |
| 5 | No confident eligibility from incomplete evidence | Baseline tests; final regression PENDING |
| 6 | Material active-program evidence improvement without weaker safety | PENDING real canary and denominator |
| 7 | One canonical support-type contract, WORKSPACE path | LOCAL PASS: Python/SQL contract parity, all 15 UI filters execute real SQL; production PENDING |
| 8 | Preserve Radar recommendation ordering | LOCAL PASS: RPC ranking retained despite reverse chronological dates; production PENDING |
| 9 | Correct explicit mixed-feed pagination | LOCAL PASS: independent GFC/Radar sections, two pages, pinned notices, no omitted/duplicate fixture items; production PENDING |
| 10 | Preferences cannot bypass channel suspension | LOCAL PASS: RPC and Python saves preserve administrative gates and BLOCKED/UNVERIFIED health; production PENDING |
| 11 | Distinct collection/persistence/documents/calculation/delivery health | LOCAL PASS: shared sanitized health projection, independent clocks and current/history denominators; production PENDING |
| 12 | Member freshness and staleness visible | LOCAL PASS: version observation, profile queue state and explicit delayed target; production PENDING |
| 13 | Actual production-safe OCR path | Native OCR PASS incl. limits; 3 real originals/15 pages extracted as drafts; Linux offline container CI PASS (run 34819471110); deployment PENDING |
| 14 | AI timeout/retry/cost/cache observability | LOCAL PASS: request metrics, persistent failure cache, short claims, concurrent/expired owner tests; live usage PENDING |
| 15 | Incremental current-result recomputation | PENDING |
| 16 | Measured 100/1,000-team growth | PENDING |
| 17 | Policy-permitted original preservation | PENDING |
| 18 | Non-production restore exercise | PENDING |
| 19 | Real authorization boundaries | PENDING controlled legitimate roles |
| 20 | Actual V1/Cloudflare control paths unambiguous | PENDING deployed-state evidence |
| 21 | Existing suites stay green | Baseline: 335 Python + 5 OCR skips; 81 GFC; 35 E2E; 4 Worker. Rerun PENDING |
| 22 | Defect-specific regressions | IN PROGRESS |
| 23 | Real source-to-member no-delivery canary | PENDING |
| 24 | Scheduled health correct after canary | PENDING |
| 25 | No unintended worker/queue/message | Final inspection PENDING |
| 26 | No unresolved critical audit finding except documented unavoidable external limits with safe degradation | PENDING all phases |

## Safety and change management

Production migrations are additive and applied only after local database verification. Preserve original failed attempts and existing source configuration. Do not enable subscriber delivery or invent subscribers. Keep user local changes/stashes. Never copy production secrets into tests or client bundles. Do not alter unrelated GFC schemas.

Implementation branches in both repositories: codex/production-hardening-20260914. No production changes have been made by this hardening run yet.

## Local verification checkpoints

- Phase 1 full native PostgreSQL: 374 passed, 5 optional OCR skipped (155.43s).
- Phase 2 targeted: 97 passed, 5 OCR skipped; subsequent native OCR/sandbox-contract run: 40 passed, 1 Linux-container test skipped.
- Phase 2 full checkpoint before the final real-source semantic guard additions: 394 passed, 1 Linux-container test skipped (257.30s).
- Radar PGlite migration/RLS/role regression PASS; Worker 4/4 PASS.
- Phase 2 Linux CI commit `26bb4974e70a99b5b129b7522848c4160384586a`: all three jobs PASS, including native OCR and actual offline/read-only/non-root container probe. Initial container model-file permission failure was fixed with read-only model permissions, not root execution.
- Phase 3 native PostgreSQL full suite: 408 passed, 1 Linux-only sandbox test skipped (215.74s). Default support type is explicitly UNKNOWN and survives cache serialization unchanged.
- Phase 3 GFC: 81 Node/DB tests PASS, 36 Playwright tests PASS (53.7s), production build PASS. The added E2E test runs actual migrations and authenticated SQL behind intercepted HTTP transport; it is not a production session test.
- Phase 3 Linux CI: Radar run 34821179068 PASS; GFC run 34821350572 PASS. Both pull requests remain drafts (#7 Radar, #10 GFC).
- Phase 4: native PostgreSQL 414 passed, 1 Linux-only skip (237.19s); GFC 81 Node/DB and 37 Playwright PASS; both DB/Worker regressions and GFC build PASS. Notification fixtures explicitly mark simulated channels healthy. No real messages were sent.
- All JUnit/logs and real-document OCR measurements are in the task workspace `startup-radar-hardening` directory. These are local evidence, not production canary proof.

## Evidence quality implementation notes

AI requests use a 90-second explicit SDK timeout, SDK retries disabled, and at most two measured provider requests per attempt. Identical transient input has three automatic attempts maximum with persistent backoff; deterministic failures are retained until input/contract changes or an explicit audited single-input retry. Unknown provider usage is recorded as unknown, not zero billed usage. Tokens are recorded without inventing currency estimates.

AI claims commit before the external call. A ten-minute expired claim is UNCERTAIN; it is never automatically re-owned. `retry-extraction --input-hash ... --note ...` authorizes one controlled retry; RUNNING/UNCERTAIN owners additionally require verified termination and `--confirm-stopped`. No notification is sent. A non-secret `RADAR_AI_CONFIGURATION_REVISION` may change when provider configuration is deliberately repaired.

The evidence container has no network, no application secrets, a read-only root, no capabilities, a non-root UID, one CPU, bounded RAM/swap/PIDs and one disposable input directory. Native Windows parsing remains a local development path, not proof of Linux production sandboxing. There is no native fallback after configured container failure.

OCR v2 uses automatic layout segmentation. Three hash-verified official originals were visually inspected in full: Pre-WoW (6 pages), Gyeonggi poster (1), and BizInfo Japanese expert program (8). v2 extracted 2,090/153/6,974 characters respectively. OCR remains imperfect and untrusted: a poster event date is not its application deadline, and expert experience is not founder age. The real-source golden corpus records these distinctions; its injected-response tests prove semantic guards, not live model accuracy. Live extraction scoring and active-program improvement remain PENDING.

Reference contracts: [Anthropic SDK errors/timeouts/retries](https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python), [Docker resource/isolation flags](https://docs.docker.com/reference/cli/docker/container/run/). Pinned repo dependency versions remain authoritative.

## Support types and feed contract

`radar.support_types` owns the normalized values, Korean labels and exact raw-source mapping. The additive migration embeds this contract and is parity-tested. GFC receives selectable values from `gfc_radar_me`; no frontend SPACE alias remains. Existing GRANT/GLOBAL identifiers are retained. Broad unmapped categories remain UNKNOWN. Raw source payloads and historical normalized JSON are not rewritten; the read projection normalizes historical categories. Source content/fingerprints remain traceable.

Before tightening profile preference validation, a read-only production check found two unset profiles and one EDUCATION preference. No profile was changed. New profile saves reject values outside the canonical contract.

The all tab is two independently paged sections, not a globally time-sorted feed. GFC notice order remains pinned/published/id; Radar preserves the exact RPC order, with recommendation score priority in recommended mode. The two-page E2E proof uses a stable 39-program/23-notice snapshot, all 15 supported categories, reversed score/date order and a pinned oldest notice. Concurrent source updates can still change an offset-based result set; this is not a snapshot-isolation or keyset-pagination guarantee.

Evidence UI separates requirement value, stored evaluation-profile input and verdict. Preset assumptions are marked. Recommendation fit is explicitly not selection/funding probability. Member/source freshness and the health dashboard are implemented on the hardening branch; production rollout remains pending.

## Notification state and recovery contract

Subscription `enabled` and per-kind flags are administrative allow gates; false means suspended/restricted. User preferences live only in `team_notification_preferences`. Both member RPC and the legacy Python preference API use the same authorized atomic SQL implementation and never update channel gates or channel health.

Channel health is UNVERIFIED, HEALTHY or BLOCKED. New unverified rows are not deliverable. A recent latest delivered receipt can backfill HEALTHY without enabling a channel; explicit documented operator verification can also establish health. Administrative configuration requires a note and records before/after, actor and timestamp without chat identifiers. A Telegram HTTP 403 marks the channel BLOCKED; preference saves cannot clear it. Administrators must separately verify the channel and lift any suspension. A user opt-out continues to block delivery after unsuspension.

Planning and pre-send revalidation require all administrative, user and channel-health gates. Already in-flight requests cannot be recalled. UNCERTAIN receipts are not automatically retried. Zero pending work returns an explicit no-op result without touching transport. Opportunity links contain only the program UUID; team context stays in the authenticated web session.

Legacy ledger/scenario validation helpers can no longer activate production channels: they reject the real Telegram transport and require the ephemeral test-database marker before any write. Their synthetic D-7/D-3 records are not natural scheduled delivery proof. Actual deployed V1/Cloudflare command isolation remains Phase 8 work.

## Health and freshness contract

Both the GFC admin RPC and Python health endpoint use one sanitized SQL projection. It keeps separate source-attempt, successful-full-scan, persistence, observation and failure clocks. A source is counted healthy only when its latest source run succeeded and a full scan is at most 24 hours old. Over 24 hours is WARNING; over 48 hours is INCIDENT; missing or implausibly future clocks are UNKNOWN. Member refresh success cannot turn failed or stale collection green.

Current and historical document denominators are separate. The quality view rechecks elapsed time on every read, reports OPEN/UPCOMING counts, D-7/D-3 backlog, per-source evidence and a prioritized review queue. Stored eligibility facts are unchanged. Primary-query advertised totals are not divided into the union of primary and targeted search results. The dashboard identifies those scopes separately.

Version creation, exact-version source observation, quality assessment and team-result computation have distinct labels in Asia/Seoul. Re-observing identical source content updates the version observation clock without rewriting or duplicating its immutable snapshot. Reviewing or revoking stored evidence inherits the original source clock, including unknown, instead of pretending a new primary-source fetch occurred. Ambiguous legacy review timestamps are not backfilled as fresh source observations.

Profile status distinguishes QUEUED, CALCULATING, READY, FAILED, STALE and NOT_CALCULATED. A successful global refresh clock survives later failures. The existing hourly worker has a provisional 90-minute operational target, not a verified SLA or five-minute promise; overdue queued/running requests are explicitly delayed. Refreshing status preserves unsaved profile edits. Stored results that no longer match the profile, response, generation or Seoul date remain hidden until recomputed.

Operator views include unresolved latest attempts, retry history, exact task/attempt/execution identifiers and recovery prerequisites. Old failures remain in the ledger after a successful retry. Channel counts and confirmed receipt time are separate from ingestion/calculation. Existing receipt origin is not fully verified, so this dashboard does not claim natural scheduled delivery acceptance.

Phase 4 remote verification: Radar run 34822972462 PASS; GFC run 34822979946 PASS. Phase 5 final native verification: 421 passed, 1 Linux-only container test skipped (197.64s), including unchanged re-observation and review/revocation clock preservation. Phase 5 GFC verification: 81 Node/DB tests, 39 browser tests and production build PASS. Radar DB/Worker regressions also PASS. Main bundle is 758.53 kB (220.14 kB gzip); route splitting and runtime measurements remain Phase 6/acceptance work. Phase 5 remote verification remains pending. No production migration, configuration change or message was made.
