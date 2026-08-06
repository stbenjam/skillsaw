---
name: summarize-diff
description: Summarize a git diff into a reviewer-facing changelog grouped by subsystem. Use when preparing a change review.
---

# Summarize Diff

Use this skill when the user asks what changed in a branch or a pull request
and wants a summary they can paste into a review.

## Steps

1. Run `git diff --stat` against the base branch to see which files changed.
2. Group the changed files by subsystem, using the top-level directory name.
3. For each group, read the diff and write one sentence describing the change.
4. Emit a markdown list with one bullet per group.

Stop once the summary is written. Do not commit, push, or open a pull request.
