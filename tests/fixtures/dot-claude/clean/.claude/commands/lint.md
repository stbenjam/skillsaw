---
description: Run the project linter and report findings
---

## Name
lint

## Synopsis
```
/lint [--fix]
```

## Description
Runs the configured linter against the current project and reports
any style or correctness violations found.

## Implementation
1. Detect the project language and linter configuration
2. Execute the linter with the current project root
3. Parse the output and present violations grouped by file
4. If `--fix` is passed, apply automatic fixes where available
