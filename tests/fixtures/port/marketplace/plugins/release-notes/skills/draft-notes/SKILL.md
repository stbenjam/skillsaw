---
name: draft-notes
description: Draft release notes from the merged pull requests since the last tag. Use when preparing a release or summarizing recent changes.
---

# Draft Notes

Collect the pull requests merged since the most recent release tag and
group them by change type before writing the summary.

## Steps

1. List merges since the last tag with `git log --merges`.
2. Group entries into features, fixes, and internal changes.
3. Write one sentence per entry, linking the pull request.
