---
name: migration-reviewer
description: Use when reviewing a database migration, to check that it is forward-only, reversible on paper, and matched by the code that reads the new columns.
---

# Migration reviewer

Review one migration in `migrations/` and report what it does and what it
misses.

## Steps

1. Read the migration and its header comment.
2. Find every column, index and constraint it adds, changes or drops.
3. Search `crates/` for code that reads each of those columns.
4. Check the header comment describes a rollback for every statement.

Report each statement that no code reads, and each statement the rollback
note does not cover.
