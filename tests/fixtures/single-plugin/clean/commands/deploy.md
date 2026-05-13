---
description: Deploy an application to the target environment
argument-hint: "[environment] [--dry-run]"
---

## Name
deployment-tools:deploy

## Synopsis
```text
/deployment-tools:deploy staging --dry-run
```

## Description
Deploys the current application build to the specified environment.
Validates configuration before deployment and runs pre-flight checks.

Supported environments are defined in `deploy.yaml`. The `--dry-run`
flag prints the deployment plan without executing it.

## Implementation
1. Read deployment configuration from `deploy.yaml`
2. Validate environment name against known environments in the config
3. Run pre-flight health checks on the target cluster using `kubectl get nodes`
4. Build the container image with `docker build -t $IMAGE_TAG .`
5. Push the image to the registry with `docker push $IMAGE_TAG`
6. Execute deployment using the configured rollout strategy
7. Wait for readiness probes to pass with `kubectl rollout status`
8. Report deployment status and any errors encountered
