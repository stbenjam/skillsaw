---
name: Format_Checker
description: Checks source files against the project style guide. Use when reviewing formatting before opening a pull request.
---

# Format checker

Check the changed files against the style guide and report deviations.

1. Collect the changed files from `git diff --name-only`.
2. Run the formatter in check mode on each file.
3. Report each deviation with its file and line.
