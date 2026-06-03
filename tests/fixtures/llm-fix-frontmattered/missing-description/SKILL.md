---
name: missing-description
---

# Missing Description Skill

Deploy a service to Kubernetes using Helm charts.

## Steps

1. Run `helm lint charts/` to verify the chart is valid
2. Run `helm upgrade --install` with the correct values
3. Run `kubectl rollout status` to confirm pods are ready
