---
name: berth-check
description: Use when a sailing has no berth assigned, to find which allocation constraint rejected it and what would satisfy that constraint.
---

# Berth check

Explain why one sailing failed berth allocation.

## Steps

1. Run `./bin/ferrymark berth explain --sailing "$SAILING_ID"`.
2. Read the rejecting constraint from the command's output.
3. Look that constraint up in `conf/berth-policy.yaml`.
4. Run the command again with `--relax "$CONSTRAINT"` to see which berth
   would have been assigned.

Report the constraint, the berth that relaxing it would free, and whether
any other sailing already holds that berth.
