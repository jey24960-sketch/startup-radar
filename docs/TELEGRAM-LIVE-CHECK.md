# Approved Telegram connection check

Use the existing configured `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` only after the recipient has been approved. No target override or arbitrary message input is accepted.

The existing registered `telegram_polling.yml` workflow has an explicit `delivery_check=true` manual mode. In this mode only the delivery-check job runs; the legacy polling job is skipped. The check calls the V2 `TelegramTransport.send` implementation once, never calls getUpdates, changes bot commands, or changes webhook configuration. It does not enable V1/V2 schedules.

```sh
gh workflow run telegram_polling.yml --ref feature/startup-radar-v2 -f delivery_check=true
```

The message is clearly labeled a StartupRadar connection check. The artifact records the delivery state and Telegram message receipt without the token or chat ID. An uncertain response is not retried. GitHub run retries cannot send again (`run_attempt` must be 1); a new manual dispatch is a separate send and requires operator intent. Inspect the existing receipt before retrying an uncertain action.

This is a transport connection check, not proof of digest/high-fit/reminder planning, persistent outbox idempotency, or partial delivery behavior. Those require the ordinary notification ledger and approved test subscriptions. Do not claim notification operating acceptance based on this message alone.
