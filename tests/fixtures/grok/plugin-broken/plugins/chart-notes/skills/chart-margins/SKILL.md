---
name: chart-margins
description: Check that a harbour chart leaves the margin the printer needs. Use when preparing a chart plate for the print shop.
---

# Chart margins

Check one chart plate against the print shop's margin requirements before
it is sent.

## Steps

1. Read the plate size and the margin from `docs/print-spec.md`.
2. Measure the distance from each annotation to the nearest plate edge.
3. Report every annotation closer than the required margin.

Report the plate size with each measurement, so a plate on the wrong stock
is obvious rather than merely failing.
