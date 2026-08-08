---
name: pr-review
description: Review the current pull request diff and summarize risky changes before approval
---

# PR Review

Review the changes shown by !`git diff HEAD` and summarize anything risky
for the reviewer. Focus on changes to authentication, migrations, and CI
configuration.

## Environment

Capture the toolchain and working-tree state first:

```!
node --version
git status --short
```

## Recent history

Compare against !`git log --oneline -5` to spot follow-up commits that
belong in the same review.
