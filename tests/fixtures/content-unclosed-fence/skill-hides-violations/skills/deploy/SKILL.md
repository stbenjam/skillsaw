---
name: deploy
description: Deploy the application to staging or production and roll back failed releases
---

# Deploy

Run deployments from a clean working tree on the main branch.

<!-- skillsaw-assert content-unclosed-fence -->
```bash
make deploy ENV=staging
make deploy ENV=production

## Rollback

Try to roll back immediately when a release fails health checks. Ideally
the pipeline reverts bad releases on its own, but if possible verify the
dashboards yourself after every deploy.
