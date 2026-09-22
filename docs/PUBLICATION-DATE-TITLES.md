# Publication-date labels

The public title names the **first publication day in Asia/Seoul**, not a source
collection period. Examples: `9월 22일자 주간 지원사업 공지` and
`9월 15일자 최초 지원사업 목록`. New and materially changed opportunities still use
the existing selection rules; this change does not claim that every opportunity
was announced by its source on that day.

`week_start` / `week_end` remain the Monday–Sunday operational identity and the
deduplication key. Historical `display_start`, `display_end` and `snapshot_date`
are retained. Published titles use `published_at`; neither the run's week nor
the current time may replace an existing publication date. An unpublished draft
has `발행 전 주간 지원사업 공지`, with no guessed date.

## Applying the change

1. Confirm that every `PUBLISHED` row has `published_at`, and no collection or
   editorial publication update is active. Record existing article, item and
   announcement counts and hashes without exposing message recipients.
2. Apply only the new forward migration
   `20260922131611_weekly_publication_date_titles.sql`. Its dependencies are the
   existing weekly/baseline tables and `admin_audit`; no new scheduler is needed.
3. The migration changes titles only and records each before/after title as
   `WEEKLY_PUBLICATION_TITLE_NORMALIZED`. It retains article IDs, first publication
   timestamps, content revisions, all item snapshots, hidden state and URLs. A
   database trigger also normalizes future publications by older workers.
4. Deploy the worker and web display changes. The worker uses the database's
   publication clock and the first persisted timestamp for explicit revisions.
   `announce()` continues reading the stored title for a **new** message.
5. Verify the existing article titles, unchanged hashes excluding title, audit
   count and member/admin visibility. Repeat the title-only update to confirm
   zero additional changed rows/audits. Do not rerun collection or delivery.

No already-created announcement payload, Telegram receipt or delivery state is
edited. Sent messages are not edited or resent; explicitly recovered failed
messages retain their original ledger payload as before. A new announcement
uses the normalized title from its article.

## Rollback

Production applied this source migration as ledger version `20260922132845`
(`weekly_publication_date_titles`) on 2026-09-22. The CLI-generated source
filename remains `20260922131611_weekly_publication_date_titles.sql`; do not
reapply it or repair old migration history to force timestamp equality.

Post-application verification found three corrected titles and three audit
records. Hashes of all briefing fields except title, all item records and the
entire announcement ledger were identical before and after the change.

The old worker is compatible with the new database trigger, so application
rollback can leave the title migration in place. If the label itself must be
reverted, stop publication writes, remove the normalization trigger in a new
forward migration, and restore only titles whose current value still equals
their audited `after_title`; restore the corresponding `before_title` and audit
the rollback. Do not overwrite later editorial changes, restore article contents
or reset announcement records. Retain the date helper until no code uses it.

## Isolated verification

- `tests/publication_titles_database.test.mjs`: synthetic historical weekly and
  baseline rows; entire records except title unchanged; item and delivery
  snapshots identical; before/after audit; repeated correction produces no new
  audit; Seoul midnight/year boundary; old-worker compatibility and role grants.
- `tests/test_publication_titles.py`: database-clock initial publication, draft
  publication, Seoul date formatting, ordinary rerun, explicit revision and
  already-delivered announcement stability.

These tests do not invoke production collection or send any real messages.
