---
name: schema-diff
description: Use when comparing the PostGIS schema in a branch against the one on main, before writing or reviewing a migration.
---

# Schema diff

Compare the schema a branch produces against `main` so a migration is
reviewed against what it actually changes.

## Steps

1. Run `make schema-dump BRANCH=main` to write `build/schema-main.sql`.
2. Run `make schema-dump` on the current checkout.
3. Diff the two dumps with `git diff --no-index build/schema-main.sql
   build/schema.sql`.
4. Read the diff against the migration in `migrations/`. Every statement
   in the diff must trace to a line in the migration.

Report any statement in the diff that the migration does not explain.
