---
name: deploy-service
description: Deploy a service to Kubernetes using Helm charts
compatibility: Requires helm, kubectl, and cluster credentials
metadata:
  author: platform-team
  version: "2.1"
---

# Deploy Service

Automates the deployment of microservices to Kubernetes clusters using
Helm charts and environment-specific value overrides.

## When to Use This Skill

Use when deploying a service to staging or production, or when updating
an existing deployment with new configuration.

## Implementation Steps

### Step 1: Validate Chart

Run `helm lint charts/` to verify the Helm chart is syntactically valid.
Check that all required values are defined in `values.yaml`:
- `image.repository`
- `image.tag`
- `replicaCount`
- `resources.limits.cpu`
- `resources.limits.memory`

### Step 2: Apply Configuration

Merge environment-specific values from `values-{env}.yaml` with the
base `values.yaml` file:
```bash
helm template my-service charts/ \
  -f charts/values.yaml \
  -f charts/values-$ENV.yaml \
  --dry-run
```

Review the rendered manifest before applying.

### Step 3: Execute Deployment

Run `helm upgrade --install` with the merged configuration:
```bash
helm upgrade --install my-service charts/ \
  -f charts/values.yaml \
  -f charts/values-$ENV.yaml \
  -n $NAMESPACE \
  --wait --timeout 300s
```

### Step 4: Verify

Run `kubectl rollout status deployment/my-service -n $NAMESPACE` to
confirm all pods are ready. Check that health endpoints return 200.

## Examples

### Example 1: Deploy to Staging

Deploy the user service to the staging cluster with default values:
```bash
helm upgrade --install user-service charts/ -f charts/values-staging.yaml -n staging
```

### Example 2: Deploy with Custom Tag

Override the image tag for a specific build:
```bash
helm upgrade --install user-service charts/ --set image.tag=abc1234 -n production
```
