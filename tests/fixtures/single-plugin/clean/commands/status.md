---
description: Show deployment status for all environments
---

## Name
deployment-tools:status

## Synopsis
```text
/deployment-tools:status
```

## Description
Displays the current deployment status for all configured environments.
Shows the running image tag, replica count, and health check results
for each environment.

## Implementation
1. Read `deploy.yaml` to get the list of configured environments
2. For each environment, run `kubectl get deployment/$APP -n $NAMESPACE -o json`
3. Extract the current image tag, ready replicas, and desired replicas
4. Run a health check against the environment's ingress URL
5. Format results as a markdown table: Environment | Image | Replicas | Health
6. Display the table to the user
