---
name: snapshot-restore
description: Point-in-time restore for the primary datastore.
---

# Restore Snapshot

Recovers the primary datastore to a chosen moment, either into the live
cluster during an incident or into a scratch namespace for analysis.

## Choosing a target time

Restores land on the write-ahead log position nearest the requested time.
[The WAL retention notes](docs/wal-retention.md) say how far back the
window reaches.

## Running the restore

`pgctl restore --at <timestamp> --into <namespace>` blocks until the
replay finishes. Progress and failure modes are described in [the restore
runbook](runbooks/pg-restore.md).
