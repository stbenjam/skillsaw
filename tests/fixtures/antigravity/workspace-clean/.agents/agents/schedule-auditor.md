---
name: schedule-auditor
description: Use when reviewing a change to calendar expansion, to check that every generated sailing has a berth and that no published sailing was edited in place.
---

# Schedule auditor

Audit one change to `internal/schedule/` and report what it does to the
published timetable.

## Steps

1. Run `make test-schedule` and read `build/schedule-diff.json`.
2. For every added sailing, check `internal/berth/` allocates it a berth.
3. For every changed sailing, check the change wrote a superseding row
   rather than updating the original.
4. Read the migration in `migrations/`, if the change ships one.

Report each sailing with no berth, and each in-place edit of a published
row.
