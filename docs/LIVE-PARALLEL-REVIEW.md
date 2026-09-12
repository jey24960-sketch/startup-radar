# Live V1/V2 comparison — 2026-09-13 KST

This is one partial operating comparison, not a cutover approval. The existing Telegram target is approved for testing, but this comparison sent no messages and did not change its delivery history. No extra role accounts are available; actual ordinary-member/external login tests remain unverified.

## Collection evidence

V1 ran its existing 13-source crawler and analyzer with `--dry` semantics. Collection ran from 02:35:20 to 02:36:05 KST and analysis ended at 02:37:39. Twelve sources returned text; Seoul Business Agency timed out. Two of three AI chunks returned invalid JSON. Five items survived the existing relevance threshold of 60. The process correctly returned 1 for partial failure. `seen_programs.json` remained unchanged.

The read-only V2 snapshot contained 19 current catalog versions. Its latest completed source runs ended at 02:03:21 (BizInfo, 3 sampled records), 01:44:51 (Korea Sejong homepage, 13 linked notices), and 02:24:01 (K-Startup, 3 sampled records). All were within the defined six-hour comparison tolerance, approximately 11–50 minutes before V1 collection. All three had partial results. These are nearby intervals, not simultaneous or equivalent collection scopes. Individual catalog items retain their own last-seen timestamps.

The V1 profile is a Seoul university startup club with an MVP, 3–5 members, and pre-business/global interests. V2 was evaluated against the existing controlled Stage 0 and Stage 4 test teams. Those profiles are not equivalent; score differences cannot establish eligibility defects.

## Investigated differences

- Automatic identity matching: 0 exact pairs, 5 V1-only and 19 V2-only records, no duplicate title+organization groups in either input. These counts are algorithm output, not missed-opportunity or national coverage rates.
- Every V1 result had the K-Startup homepage as its application URL. The V1 HTML text extraction removes link attributes, and the analyzer supplied generic URLs. A homepage/shared listing cannot establish program identity. The comparator now excludes those URL matches.
- The IR Round (3rd) notice exists in both inputs with the same title. V1 organization is `서울창업허브 창동 / (주)오픈놀`; V2 has `서울창업허브 창동`. It remains an explicit manual-review candidate instead of being silently merged. A fresh official-list inspection exposed publisher ID 179222 for that title, consistent with the V2 canonical detail.
- Both IR records state September 30 as the deadline date. V2 additionally retains 17:00 KST from official detail. V1 cannot verify that time. V1 relevance 60 is not formal eligibility; V2 reports UNVERIFIABLE with incomplete document and condition evidence for the tested teams.
- Official-list inspection also exposed SVC Seoul expanded membership (178802), global membership (178803), and the integrated government announcement (175783). They are absent from the current three-record K-Startup V2 sample. This demonstrates a sample coverage gap, not proof that the full adapter cannot discover them. The remaining V1 “모두의 창업 프로젝트 2차” item has not been independently matched to an official detail in this review.
- V2 contains BizInfo and Korea Sejong notices outside V1's identical source scope, plus historical/general notices. V1 first filters for current/upcoming items and relevance. Raw differences therefore mix source coverage, sampling, catalog age, AI omissions and profile filtering.
- Source failures remain visible: V1 has one failed acquisition and two malformed AI chunks. V2 has page limits, document parsing and AI evidence/schema failures in the recorded runs. The two systems' failures must not be described as “no relevant programs.”
- Notification behavior in this comparison is delivery-disabled. Earlier one-message Telegram connectivity evidence does not validate digest/high-fit/D-7/D-3 planning, receipts or idempotency.

## Comparison implementation

`main.py --dry` now requires only the AI credential; normal delivery still requires both Telegram settings. Run reports preserve collection intervals, the configured/acquired sources, the explicit V1 profile and relevance threshold. `all_programs` means pre-send-history filtering, not all discoveries or unfiltered AI output.

`radar.cli compare` remains read-only. Its `parallel-2.0.1` report includes per-source run IDs/intervals/counts, per-program last-seen observations, deadline precision/date review, profile context and exact-title manual candidates. A fresh global ingestion timestamp cannot conceal a stale or unfinished individual source. Source failures are projected to kinds so exception strings cannot leak credentials into reports. No comparison sets `cutover_approved` to true.

## Next operating evidence

Repeat with an explicitly bounded common publisher cohort and aligned, non-personal test profiles; preserve every source's failures and sampled scope. Independently inspect conditions, attachments and deadline disagreements. Validate actual notification planning/delivery with the approved target. Ordinary-member/external login, mobile behavior and production cutover remain open. V1 stays in place and V2 schedules remain disabled.
