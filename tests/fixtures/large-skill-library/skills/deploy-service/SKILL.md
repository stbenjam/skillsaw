---
name: deploy-service
description: Deployment helper for the payments service.
---

# Deploy Service

Promotes a build from staging to production behind the payments feature
flag. The rollout is gradual: 5% of traffic, then 50%, then everything.

## Steps

1. Confirm the staging smoke tests are green — see [the smoke test
   guide](docs/smoke-tests.md).
2. Promote the build with `payctl promote --canary`.
3. Watch the error-rate dashboard for ten minutes.
4. Roll forward, or follow [the rollback
   runbook](runbooks/payments-rollback.md).

Escalate to the on-call engineer named in [the rota](docs/on-call.md) when
the error rate crosses 0.5%.
