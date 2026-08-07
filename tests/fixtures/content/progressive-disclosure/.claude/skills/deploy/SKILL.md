---
name: deploy
description: Deploy sprocketd to staging and production. Use when releasing a new build or promoting a staged one.
---

# Deploy

Push the build to the staging channel and watch the soak dashboard for
thirty minutes. The error-rate panel is the one that matters; ignore
the latency panel during the first ten minutes because cache warmup
dominates it. If error rate stays under half a percent, request a
signed manifest from the release captain.

Promotion happens one region at a time, smallest first. After each
region, wait for the reconciliation job to complete a full cycle
before starting the next; overlapping cycles double-write inventory
rows and the cleanup is manual. If any region shows elevated 5xx after
promotion, halt the rollout, revert that region, and page the on-call
before touching the remaining regions.

Rollbacks reuse the previous signed manifest, which stays valid for
seven days. Past seven days there is no fast rollback: a new build
must go through the full staging soak again, so treat day-seven
promotions with extra care and never promote on a Friday.
