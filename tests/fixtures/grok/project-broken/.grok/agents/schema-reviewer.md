---
description: Use when reviewing a database migration, to check that it is forward-only and matched by the code that reads the new columns.
model: grok-code-fast-1
---

# Schema reviewer

Review one migration in `migrations/` and report what it does and what it
misses.

## Steps

1. Read the migration and its header comment.
2. Find every column, index and constraint it adds, changes or drops.
3. Search `waypoint/` for code that reads each of those columns.

Report each statement that no code reads.
