---
name: gateway-reviewer
description: Review card gateway changes for retry and idempotency bugs. Use for diffs under internal/gateway/.
---

Check that every network call is retried with backoff and carries an
idempotency key.
