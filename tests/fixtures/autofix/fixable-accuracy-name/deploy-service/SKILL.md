---
name: >-
  Deploy_Service
description: Deploys the service to staging and production. Use when a release has been approved for rollout.
---

# Deploy the service

Run the deployment pipeline for the requested environment.

1. Verify the release tag exists and CI is green.
2. Run `scripts/deploy.sh <environment> <tag>`.
3. Watch the health dashboard until all pods report ready.
