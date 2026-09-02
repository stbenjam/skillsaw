---
name: cluster-scaling
description: Capacity changes for the shared Kubernetes clusters.
---

# Scale Cluster

Adds or removes node capacity, and adjusts the autoscaler bounds that
decide how far it can move on its own.

## Before changing anything

Read the current headroom from [the capacity
dashboard](docs/capacity-dashboard.md). A cluster under 20% headroom at
peak is scaled up before any other change.

## Making the change

Node pools are declared in [the cluster
manifest](config/node-pools.yaml). Change the manifest, not the live
cluster; the reconciler reverts manual edits within ten minutes.
