---
name: deploy
description: Deploy applications to Kubernetes clusters
compatibility: Requires helm, kubectl, and cluster credentials
metadata:
  author: platform-team
  version: "2.0"
---

# Deploy

Handles deployment of containerized applications to Kubernetes using
Helm charts and environment-specific value overrides.

## When to Use This Skill

Use when deploying or updating services in staging or production
environments.

## Implementation Steps

### Step 1: Validate

Run `helm lint charts/` to verify the chart is syntactically valid.
Check that all required values are defined:
- `image.repository` and `image.tag`
- `replicaCount`
- `resources.limits`

### Step 2: Build and Push

Build the container image and push to the registry:
```bash
docker build -t $REGISTRY/$APP:$TAG .
docker push $REGISTRY/$APP:$TAG
```

### Step 3: Deploy

Run `helm upgrade --install` with the target namespace:
```bash
helm upgrade --install $APP charts/ \
  -f charts/values.yaml \
  -f charts/values-$ENV.yaml \
  -n $NAMESPACE --wait
```

### Step 4: Verify

Check rollout status and health endpoints:
```bash
kubectl rollout status deployment/$APP -n $NAMESPACE
curl -sf https://$APP.$DOMAIN/health
```
