---
description: Ship the approved release to an environment
---

# Ship a release

Deploy the release named in `$ARGUMENTS` to the requested environment.

1. Confirm the release tag exists and its CI run is green.
2. Trigger the deployment pipeline for the environment.
3. Watch the rollout until every instance reports healthy.
