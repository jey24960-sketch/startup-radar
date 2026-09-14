# GFC Weekly Briefing

This supersedes the production-hardening completion priorities on 2026-09-14.
Normal production is official APIs -> one weekly publication -> one Telegram announcement.
Personalization, OCR, archives of original binaries and scale benchmarks are deferred, not deleted.

## Schedule and Operations

The publication calendar is `startup_radar.weekly_schedule`, editable by a verified GFC
administrator at `/radar/weekly-admin`. Its initial value is Tuesday 15:00 Asia/Seoul.
Administrators can select any weekday and minute, or pause future automatic publication.
`.github/workflows/startup_radar_v2.yml` checks this calendar every 15 minutes with `weekly --scheduled`.
Only a due week collects and publishes; other checks return immediately without source collection or delivery.
GitHub may start late and acquisition takes additional time; this is not an exact-minute guarantee.
`RADAR_V2_ENABLED` remains the master gate for scheduled execution.
Daily ingestion, high-fit, D-7/D-3 delivery and hourly team recalculation are not on this path.
The prior `scheduling` database value is preserved in the cutover audit, then disabled.

The new calendar does not re-enable the old daily/hourly team scheduler. Changing the calendar
does not cancel an already claimed execution. If this week's newly selected time is already past,
the next check may publish immediately. A published week is never automatically republished.
One durable automatic attempt is recorded per Seoul week; failed/uncertain attempts require
operator inspection and an explicit manual `weekly` run. Missed prior weeks are not backfilled.
This uses up to 96 lightweight Actions checks daily; dependency setup still consumes runner minutes.

## Administrator editing

GFC notices -> **주간 공지 관리** opens the schedule form and a paged list of published issues.
An issue's **내용 정정** link also opens its editor. The editor supports the issue title/summary
and each existing item's title, organization, support/applicant description, deadline and official/application links.
Dates are entered in Korea time; an unknown deadline can be restored explicitly.
Adding/removing source records or changing original eligibility facts is outside this editorial form.

Corrections require a 5..500-character reason. They update the member-facing article immediately
and retain its ID, publication time, original source version and material hash. Actor, before/after
content and reason are recorded in `admin_audit`. The source comparison hash remains unchanged,
so a wording correction is not falsely presented as a new official change in the next issue.
Already delivered Telegram messages are neither edited nor resent. Pending messages use the latest
article text when claimed; a correction is rejected while an announcement is SENDING.
Both schedule saves and corrections check the expected revision and reject stale concurrent edits.
The UI retains unsaved input on rejection; copy it before choosing to reload.

Deployment order: apply `20260914153311_weekly_admin_controls.sql` from this repository first,
then deploy the GFC UI and this workflow/worker together. The GFC copy under tests/fixtures is
test input only, not a second production migration. Deploying the UI alone cannot enable these controls.
Keep the master schedule gate paused during a controlled cutover if a publication is not intended;
restore the previously authorized state after deployment. No test should send real Telegram messages.

Privileged operator commands, with the existing server credentials:

```text
python -m radar.cli weekly --draft
python -m radar.cli weekly
python -m radar.cli weekly --deliver
python -m radar.cli weekly --revision-note "Reason for verified correction"
python -m radar.cli execution-status
```

`--draft` rebuilds only an unpublished current-week draft. The normal command publishes.
A published week is stable: ordinary reruns return its existing ID and do not recollect or rewrite it.
Only an explicit `--revision-note` recollects/revises the current issue. Prior item snapshots and version links
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

Successful complete empty acquisition may publish a no-new-or-changed-opportunities issue.
All-source failure never publishes an empty issue. Partial acquisition may publish valid useful items,
retaining `PARTIAL_SUCCESS` internally and a nonzero CLI exit for operator visibility.
An incomplete empty result does not publish. Existing safety caps remain explicit limits, not national coverage.

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
