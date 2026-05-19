---
description: Synchronize data between two configured endpoints
argument-hint: "<source> <destination> [--dry-run]"
---

## Name
data-fetcher:sync

## Synopsis
```text
/data-fetcher:sync users-api local-db --dry-run
```

## Description
Synchronizes data from a source endpoint to a destination. Supports
incremental sync using the `last_sync` timestamp stored in
`.sync-state.json`.

## Implementation
1. Read the source and destination endpoint configurations
2. Load the last sync timestamp from `.sync-state.json`
3. Fetch records from the source that changed since the last sync
4. Transform records to match the destination schema
5. Write records to the destination in batches of 100
6. Update `.sync-state.json` with the current timestamp
7. Report the number of records synced and any failures
