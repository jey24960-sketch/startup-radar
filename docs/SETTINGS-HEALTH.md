# Preferences and admin health: Phase A completion

Python API status: **A. NOT REQUIRED** for all required GFC member and essential admin behavior. Migration `20260912143423_gfc_radar_preferences_and_health.sql` is applied individually to shared project `etvffzxqdgblvkfdikwl`; GFC fixture copies are test-only.

## Preferences

GET/PUT `/api/teams/{id}/preferences` map to `gfc_radar_preferences` / `gfc_radar_save_preferences`. Existing Supabase JWT, `public.my_role()` and explicit Radar membership checks apply. VIEWER reads; OWNER/EDITOR writes. A non-member with a stray Radar membership is denied.

Save accepts exactly four booleans: enabled, digest_enabled, alerts_enabled, reminders_enabled. Null, missing, extra and wrongly typed fields are rejected. Team preferences, existing channel flags and an audit record commit together. An unconnected team can save; the response exposes connection status and flags, never chat IDs or transport payloads.

These are team-common preferences. The worker gives stored team flags precedence over channel flags, checks them when planning and when claiming a send, and cancels a pending batch when disabled. Direct authorized RLS preference writes therefore take effect even without channel synchronization. A network send already claimed as SENDING cannot be recalled by a later preference change. No actual notification was sent in this validation.

## Health

GET `/api/admin/health` maps to `gfc_radar_health`. It requires the existing GFC admin role; no separate legacy Radar admin mapping is needed. The safe projection includes source attempt/success, discovered/fetched/parsed counts, latency, typed failure kinds, recent runs, document/eligibility failure counts, calculation state, queue counts and schedule flags. Raw error messages, source config, tokens, URLs embedded in diagnostics and team/user identifiers are omitted. Unknown values appear as unknown, not a false successful zero. Monitored source success is not nationwide coverage.

## Authorization and verification

Three public SECURITY INVOKER wrappers call two private SECURITY DEFINER functions. Privileged helpers are needed for protected subscription/audit and health data; they use an empty search_path, qualified names and explicit auth/member/team or admin checks. EXECUTE is revoked from PUBLIC, anon and service_role and granted only to authenticated on these exact five functions. Existing table grants and RLS are unchanged. startup_radar is not exposed through the Data API.

Native PostgreSQL tests cover invalid input, cross-team denial, VIEWER behavior, preference enforcement before transport, safe diagnostics and GFC admin access. Eleven grouped actual shared-DB checks passed and rolled back all synthetic rows. Anonymous REST returns 401 for all three wrappers. Existing 1,085 GFC/Auth/Storage metadata objects are unchanged; three public wrapper functions were added. Security advisor results are unchanged.

All 15 browser tests run with an empty Python origin; preferences survive reload and admin health displays failures without HTTP fallback. These use synthetic Auth/REST fixtures. Real OAuth accounts, source-to-member flow, approved notifications and matched-period V1/V2 comparison remain unverified. V2 scheduling remains disabled.
