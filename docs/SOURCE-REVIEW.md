# Member explanations for source conditions

The program detail RPC exposes `source_review` for its selected notice version.
It projects the latest source snapshot per source into `kind`, up to three short
`quotes` (500 characters each), and `source_url`; at most 50 distinct findings are
returned. Unknown reason codes become `UNCLASSIFIED_REVIEW`. Malformed metadata
does not break detail reads. Old versions retain their own findings.

The raw source snapshots contain administrator-only configuration/diagnostics.
They remain administrator-only. `startup_radar.member_source_review(uuid)` is a
private SECURITY DEFINER projection with an empty search path, explicit non-null
Auth identity and protected GFC member/admin role checks. PUBLIC/anon execution
is revoked. This narrowly scoped projection is needed to expose member-readable
explanations without broadening raw-table RLS. It contains no team data or writes.
The public detail RPC remains SECURITY INVOKER and preserves the existing team
scope authorization, signature and grants.

GFC renders the supported reasons in Korean with plain-text quotes and safe
HTTP(S) source links. Reasons distinguish ambiguous business categories, free-form
exclusion/history fields, pre-business alternatives, announcement-date business
age, and future registration/relocation commitments. Unknown kinds get a generic
review explanation. Source limitations remain visible during pending calculation
and do not override confirmed ineligibility or create recommendations.

This is an explanation of conservative review findings, not an implementation of
the unsupported conditions. It does not certify complete extraction coverage.
An empty findings array does not prove that the notice evidence is complete;
the eligibility result and document state remain authoritative. User profile
questions address missing user facts separately. Filling them does not resolve a
source interpretation limitation.

Migration: `20260912193318_gfc_radar_source_review.sql`. It adds the private helper
and replaces only the existing public detail implementation. No existing table,
RLS policy, user identity, profile, schedule, or public Auth object is changed.
Frontend fixture copies are for regression tests only, never a second deployment.

Regression coverage: ordinary-member access to the bounded projection while raw
snapshots remain invisible; external denial including direct helper execution;
anonymous ACL denial; team isolation; selected-version scope; latest observation;
malformed/unknown metadata; bounded quotes; no arbitrary metadata fields; browser
hard-failure and pending precedence, safe links/plain text, history and 390px layout.

The final operational acceptance still requires useful current opportunities,
actual role/mobile verification where available, notification scenarios and
matched repeated V1/V2 comparison before cutover.
