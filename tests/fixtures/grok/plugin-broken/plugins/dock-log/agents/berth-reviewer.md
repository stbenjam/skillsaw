---
name: berth-reviewer
description: Use when reviewing a berth allocation change, to check that every vessel still has a berth long enough for it.
---

# Berth reviewer

Review one change to the berth allocation table and report what it breaks.

## Steps

1. Read the allocation before and after the change.
2. For every vessel that moved, compare its length against the new berth.
3. Report each vessel whose new berth is shorter than the vessel.

Report the berth and the vessel length together, so the margin is visible
rather than implied.
