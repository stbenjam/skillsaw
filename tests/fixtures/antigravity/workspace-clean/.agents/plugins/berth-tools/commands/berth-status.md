---
description: Report berth occupancy for one day and flag every unallocated sailing
---

# Berth status

Report berth occupancy for the day named in the request.

1. Run `./bin/ferrymark berth status --date "$DATE"`.
2. Read the occupancy table and the unallocated list from its output.
3. Compare occupancy against the quay capacity in `conf/berth-policy.yaml`.

Report the date, the occupancy per quay, and every unallocated sailing with
the constraint that rejected it.
