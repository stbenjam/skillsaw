---
description: Deploy the current release to production
---

## Name
release-tools:deploy-prod

## Synopsis
```
/release-tools:deploy-prod [version]
```

## Description
Deploys the specified version (default: latest tagged release) to the
production environment after running the smoke-test suite.

## Implementation
1. Verify the working tree is clean and the tag exists.
2. Run the smoke tests with `make smoke`.
3. Trigger the deployment pipeline for the requested version.
4. Report the pipeline URL.
