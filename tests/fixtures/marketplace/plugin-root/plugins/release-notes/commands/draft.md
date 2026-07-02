---
description: Draft release notes from merged pull requests since the last tag
argument-hint: "[--since v1.2.3]"
---

## Name
release-notes:draft

## Synopsis
```text
/release-notes:draft --since v1.2.3
```

## Description
Collects merged pull requests since the last release tag and drafts
release notes grouped by change type (features, fixes, docs).

The plugin metadata for this plugin lives in marketplace.json with
`strict: false`, so it has no plugin.json manifest of its own.

## Implementation
1. Determine the base tag from `--since` or the most recent git tag
2. List merged pull requests since that tag using `gh pr list`
3. Group entries by conventional-commit type
4. Write the draft to `RELEASE_NOTES.md` for review
