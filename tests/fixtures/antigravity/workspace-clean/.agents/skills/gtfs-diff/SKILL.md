---
name: gtfs-diff
description: Use when comparing a generated GTFS feed against the last published one, before releasing a timetable change.
---

# GTFS diff

Compare the feed a branch generates against the published feed so a
timetable change is reviewed against what riders will actually see.

## Steps

1. Run `make gtfs-export FEED=published` to write `build/gtfs-published/`.
2. Run `make gtfs-export` on the current checkout.
3. Diff the two directories with `git diff --no-index build/gtfs-published
   build/gtfs`.
4. Read the diff against the change under `internal/schedule/`. Every
   changed row must trace to a line in that change.

Report every changed row the change does not explain, and every route
whose first or last sailing of the day moved.
