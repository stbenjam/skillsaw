---
name: review-migration
description: Review database migrations for compatibility with deployed readers. Use when planning a schema rollout.
---

# Migration review

Read the proposed migration and identify columns used by the previous release.
Explain the rollout order needed to keep those readers working. Record the
rollback procedure and identify any data that must be restored separately.
