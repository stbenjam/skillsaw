---
name: ui-test
description: Browser-based UI test execution against live clusters
user-invocable: true
allowedTools:
  - Bash(python3 *scripts/run_tests.py*)
  - Bash(python3 *scripts/collect_results.py*)
  - Read
  - Write
---

# UI Test Runner

Runs browser-based UI tests against live clusters.

## Steps

1. Run scripts/run_tests.py to execute all UI tests
2. Collect results with the results collector
