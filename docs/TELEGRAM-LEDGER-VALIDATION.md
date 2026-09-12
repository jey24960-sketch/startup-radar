# Telegram ledger validation

The existing recipient has been explicitly approved by the user. A prior connection message does not establish notification ledger correctness. This manual procedure uses one existing `운영 검증용 ` team, real stored recommendations and the existing TELEGRAM_CHAT_ID secret. It never fetches bot updates or changes the webhook.

`telegram_polling.yml` accepts mutually exclusive `delivery_check` (old connection message) and `ledger_check` (`none`, `prepare`, `deliver`) modes. Both ledger phases require the existing validation team UUID. The poll job is skipped for either validation mode. Rerun attempts are refused.

Prerequisites: RADAR_DATABASE_URL points to the existing shared-project session pooler; Telegram credentials already exist; V2 schedules remain disabled; all four team notification flags are off; the team has no other channel or pending validation history. The workflow explicitly selects the reviewed GFC preview notice URL through RADAR_MEMBER_NOTICE_URL. Production messages otherwise use the default GFC /notice URL.

1. `prepare` registers an initially disabled subscription for this test team if needed. Under the existing global job lock, it temporarily enables digest only, uses the ordinary planner, and requires exactly one real notice in one batch. A second planning call must add zero items. The batch is marked visibly as an operating check. Its text is saved in the workflow artifact for review. No Telegram transport is created.
2. Inspect the artifact: correct existing team, real notice, conditional eligibility label, original source link, GFC preview link and reasonable deadline. This is the concrete message to be sent.
3. `deliver` accepts only that single pending prepared batch. The ordinary delivery path rechecks the latest program/profile and both channel/team flags. A one-message transport additionally restricts exact recipient and text. Receipts map to actual items. Replanning and another scoped delivery must produce no additional send.
4. In either phase, `finally` restores all subscription and team notification flags to off. An `always()` cleanup step uses a same-run marker written only after preflight, so a terminated process can also restore the exact test scope. On total runner loss, inspect the marker/state and restore the validation team's flags before other operations. V2 schedules remain disabled throughout.

DELIVERED, FAILED and UNCERTAIN are terminal for this validation command: a later invocation cannot blindly resend them. Recovery of an ambiguous production delivery remains a separate audited administrative operation. No validation result authorizes enabling automatic schedules or switching from V1.

Notification planning and delivery now accept an optional subscription_id. The default retains all-subscription batch operation. Scoped runs never plan or claim another channel. A channel's disabled setting cannot be overridden by enabled team preferences: both layers must allow the notification, including each digest/alert/reminder flag.

Local PostgreSQL regression tests cover isolated subscription planning/claiming, disabled channel overrides, prepare-without-transport, successful/rejected/uncertain receipts, a second zero-send pass, repeat-invocation refusal and preference restoration. Synthetic tests are separate from real-source live acceptance. D-7/D-3, high-fit and full production scheduling still require their own operating evidence.
