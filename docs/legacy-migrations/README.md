# Archived predeployment migrations

These five files describe the original local-only `radar` schema checkpoint.
They were never applied to the shared GFC project `etvffzxqdgblvkfdikwl`.
They are preserved for history, outside the executable migration directory.

The shared GFC baseline in `supabase/migrations` creates the same final model
under `startup_radar`, with scheduling paused. It folds earlier constraint
replacements into the initial definitions so no DROP or destructive ALTER is
needed. Do not apply this archive to the GFC database. Do not rename or drop any
existing hosted schema to make a migration pass.
