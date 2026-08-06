---
name: rollout
description: Walk a deployment through staging, canary, and the full fleet. Use when releasing a service to production.
---

# Rollout

Deploy in three stages, verifying health between each.

## Steps

1. Deploy to staging and run the smoke suite.
2. Promote to the canary group and watch error rates for ten minutes.
3. Roll out to the full fleet, one zone at a time.
