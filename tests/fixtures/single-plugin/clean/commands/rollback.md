---
description: Roll back the most recent deployment
argument-hint: "[environment]"
---

## Name
deployment-tools:rollback

## Synopsis
```
/deployment-tools:rollback production
```

## Description
Rolls back the most recent deployment in the specified environment.
Identifies the previous healthy revision from the deployment history
and redeploys it.

## Implementation
1. Run `kubectl rollout history deployment/$APP -n $NAMESPACE` to list revisions
2. Identify the previous revision number
3. Show the user what will change with `kubectl rollout undo --dry-run`
4. Confirm with the user before proceeding
5. Run `kubectl rollout undo deployment/$APP -n $NAMESPACE`
6. Wait for rollout to complete with `kubectl rollout status`
7. Verify health checks pass on the rolled-back version
