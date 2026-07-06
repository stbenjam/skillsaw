---
description: Ship the current branch to staging and run the smoke suite
---

Deploy the current branch to the staging environment.

1. Verify the working tree is clean; abort if there are uncommitted changes.
2. Push the branch and wait for CI to pass.
3. Run `platform deploy staging --commit HEAD`.
4. Run the smoke suite against staging and report the results.
