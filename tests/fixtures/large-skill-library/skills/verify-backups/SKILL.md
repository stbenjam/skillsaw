---
name: verify-backups
description: Backup restore verification for stateful services.
---

# Verify Backups

Proves a backup can be restored, on a schedule, into a throwaway
environment.

## Monthly drill

1. Pick the newest full backup and one incremental.
2. Restore into a fresh namespace.
3. Run the consistency checks in [the check
   script](scripts/checks.sql).
4. Record the restore duration.

A restore that runs longer than the recovery time objective is an
incident, not a note. Report it through [the RTO
tracker](docs/rto-tracker.md).
