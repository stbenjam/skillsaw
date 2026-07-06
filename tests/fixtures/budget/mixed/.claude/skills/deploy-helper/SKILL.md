---
name: deploy-helper
description: Deploy the order-processing service to staging or production. Use when asked to ship, release, or roll out a build, or to check whether a deploy went out cleanly.
---

# Deploy Helper

Deploy the service with the platform CLI. Always deploy to staging first and
verify health before promoting to production.

## Steps

1. Confirm the working tree is clean and CI is green on the target commit.
2. Run `platform deploy staging --commit <sha>` and wait for the rollout to
   complete.
3. Check `platform status staging` — every pod should report healthy within
   five minutes.
4. Run the smoke suite: `uv run pytest tests/smoke --base-url
   https://staging.example.com`.
5. Promote with `platform deploy production --from staging` once smoke tests
   pass.
6. Watch the error-rate dashboard for ten minutes after the production
   rollout. Roll back with `platform rollback production` if the rate rises
   above 0.5%.

See [the release checklist](references/checklist.md) for the full
pre-deploy checklist.
