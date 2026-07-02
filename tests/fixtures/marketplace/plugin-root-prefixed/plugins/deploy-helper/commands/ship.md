---
description: Deploy the current service to a target environment
argument-hint: "[environment] [--dry-run]"
---

## Name
deploy-helper:ship

## Synopsis
```text
/deploy-helper:ship staging --dry-run
```

## Description
Deploys the current service to the requested environment. A dry run prints
the deployment plan without applying it.

## Implementation
1. Read the deployment manifest from `deploy.yaml`
2. Validate the target environment exists in the manifest
3. Build the release artifact and tag it with the git revision
4. Apply the deployment, or print the plan when `--dry-run` is set
5. Report the rollout status when the deployment completes
