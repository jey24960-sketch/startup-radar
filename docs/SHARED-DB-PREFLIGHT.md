# Shared GFC database preflight — 2026-09-12

Target: `etvffzxqdgblvkfdikwl` (`jey24960-sketch's Project`).
New application schema: `startup_radar`. Existing GFC Auth configuration remains unchanged.

The read-only inventory captured 48 relations, 426 columns, 175 constraints,
134 indexes, 70 functions/procedures, 114 types, 14 non-internal triggers and
32 policies across public, auction_private, auth and storage. It also inspected
24 default-privilege entries and 7 global event triggers. A second snapshot
matched the first exactly before migration. The reusable catalog query is
`tools/sql/shared_project_inventory.sql`; full definitions are retained only in
the local audit workspace because they belong to the separate GFC project.

There is no existing `radar` or `startup_radar` schema. The shared project has
10 existing GFC migration-history entries; none is a StartupRadar migration.
Do not run a bulk `supabase db push` or repair the shared migration history from
this independent repository. Apply only the reviewed StartupRadar migration.

The 28-table baseline is additive within startup_radar. Its 178 SQL statements
include no DROP, TRUNCATE, destructive ALTER, existing-schema DML, Auth settings,
existing GFC policy changes, new extensions, or changes to public.teams,
public.profiles or public.projects. Public/anon ACL revocations target only new
startup_radar objects. The only cross-schema dependencies are auth.users foreign
keys and auth.uid() in policies. These foreign keys install PostgreSQL internal
referential-integrity triggers on auth.users; they do not modify GFC's existing
user-created Auth triggers. Deleting an Auth identity cascades only its Radar
membership/admin mappings; nullable job/audit actor references become NULL so
Radar history does not prevent GFC account deletion. Team data retention is a
separate operational decision.

Tables in this schema have RLS explicitly enabled. The existing automatic RLS
event trigger only targets public, so the baseline does not rely on it. Existing
PostgREST DDL notifications may reload its schema cache after commit, but do not
change GFC tables/policies. No Data API exposure setting is changed.

The migration uses BEGIN/COMMIT, a 2-second lock timeout and a 30-second statement
timeout. If a shared Auth FK cannot acquire its lock quickly, the whole migration
must fail and be inspected. It must not be blindly retried with longer locks.
Scheduling and ingestion start paused; there are no Telegram subscriptions.

Before applying, the new baseline passed a fresh local PGlite migration/RLS
check and native PostgreSQL integration/concurrency verification. The former
radar migrations are retained in docs/legacy-migrations outside the executable
directory. Code queries now explicitly target startup_radar; Python package
imports remain radar.*. No GFC frontend code has been changed.

Existing security advisories were recorded before changes: three tables with
RLS but no policies, 37 authenticated-callable SECURITY DEFINER functions, and
disabled leaked-password protection. These belong to the existing GFC service;
they are not automatically altered as part of this migration. A callable
SECURITY DEFINER advisory alone does not establish exploitable access; function
authorization must be assessed separately. See the Supabase remediation docs:
[RLS without policies](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy),
[function execution](https://supabase.com/docs/guides/database/database-linter?lint=0029_authenticated_security_definer_function_executable),
[password protection](https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection).

The public GFC homepage and Projects page were checked before migration; the
Projects page displayed its five project records. Existing-table row counts and
content fingerprints were captured for profiles, projects, teams, problems,
settings, auction_settings and coin_investments for post-migration comparison.
