---
name: changelog-writer
description: Draft changelog entries from merged pull requests since the last release tag
compatibility: Requires git and gh CLI
metadata:
  author: dx-team
  version: "1.0"
---

# Changelog Writer

Draft changelog entries by summarizing merged pull requests since the
last release tag.

## When to Use This Skill

Use when the user asks to prepare release notes, update CHANGELOG.md,
or summarize what shipped since the last release.

## Implementation Steps

### Step 1: Find the Last Release Tag

```bash
git describe --tags --abbrev=0
```

### Step 2: List Merged PRs Since the Tag

```bash
gh pr list --state merged --search "merged:>$(git log -1 --format=%cI $(git describe --tags --abbrev=0))"
```

### Step 3: Draft Entries

Group PRs into sections:
- **Added** — new features and rules
- **Fixed** — bug fixes
- **Changed** — behavior changes and deprecations

Write one line per PR: a user-facing summary followed by the PR number
in parentheses. Skip PRs labeled `internal` or `ci`.
