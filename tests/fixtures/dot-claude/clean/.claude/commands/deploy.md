---
description: Deploy the current branch to the specified environment
argument-hint: "<environment>"
---

## Name
deploy

## Synopsis
```
/deploy staging
/deploy production
```

## Description
Deploys the current branch to the specified environment after verifying
CI checks have passed and the working tree is clean.

## Implementation
1. Run `git status --porcelain` to verify a clean working tree
2. Run `gh run list --branch $(git branch --show-current) --limit 1 --json conclusion` to check CI
3. If CI is not green, abort with an error message
4. Run `./scripts/deploy.sh $ENVIRONMENT` to trigger the deployment
5. Wait for the health check endpoint to return HTTP 200
6. Report the deployment URL and status to the user
