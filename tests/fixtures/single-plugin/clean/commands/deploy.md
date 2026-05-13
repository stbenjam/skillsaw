---
description: Deploy an application to the target environment
argument-hint: "[environment] [--dry-run]"
---

## Name
deployment-tools:deploy

## Synopsis
```
/deployment-tools:deploy staging --dry-run
```

## Description
Deploys the current application build to the specified environment.
Validates configuration before deployment and runs pre-flight checks.

## Implementation
1. Read deployment configuration from `deploy.yaml`
2. Validate environment name against known environments
3. Run pre-flight health checks on the target cluster
4. Execute deployment using the configured rollout strategy
5. Wait for readiness probes to pass
6. Report deployment status and any errors encountered
