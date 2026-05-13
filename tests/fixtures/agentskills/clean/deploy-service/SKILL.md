---
name: deploy-service
description: Deploy a service to Kubernetes using Helm charts
---

# Deploy Service

Automates the deployment of microservices to Kubernetes clusters using
Helm charts and environment-specific value overrides.

## When to Use This Skill

Use when deploying a service to staging or production, or when updating
an existing deployment with new configuration.

## Implementation Steps

### Step 1: Validate Chart

Ensure the Helm chart in `charts/` is syntactically valid and all
required values are provided.

### Step 2: Apply Configuration

Merge environment-specific values from `values-{env}.yaml` with the
base `values.yaml` file.

### Step 3: Execute Deployment

Run `helm upgrade --install` with the merged configuration and wait
for rollout completion.

## Examples

### Example 1: Deploy to Staging

Deploy the user service to the staging cluster with default values.
