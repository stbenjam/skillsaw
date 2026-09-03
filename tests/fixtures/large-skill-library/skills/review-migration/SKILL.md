---
name: review-migration
description: Reviews database migrations before they merge.
---

# Review Migration

Checks a pending migration for locks, backfills, and rollback safety
before it reaches the deploy queue.

## What to check

1. Does the migration take an exclusive lock on a table larger than a
   million rows? See [the locking notes](docs/postgres-locking.md).
2. Is the backfill batched, with a bounded batch size?
3. Can the migration be reverted without data loss?

A migration that fails any of these gets a written explanation on the pull
request, using [the review template](templates/review-template.md).

Prior decisions are recorded in [the migration log](docs/migration-log.md).
