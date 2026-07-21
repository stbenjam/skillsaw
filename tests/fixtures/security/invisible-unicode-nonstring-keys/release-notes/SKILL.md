---
name: release-notes
description: Draft release notes from merged pull requests since the last tag
compatibility: Requires git and gh CLI
2024: archived milestones live under docs/archive/2024
2024-06-30: last audit of the release checklist
on: workflow_dispatch
metadata: &meta
  author: release-team
  version: "1.2"
  history: *meta
---

# Release Notes

Draft release notes by collecting merged pull requests since the most
recent tag and grouping them by change type.

## When to Use This Skill

Use when the user asks to draft release notes, summarize changes since a
release, or prepare a changelog entry.

## Implementation Steps

### Step 1: Find the Last Tag

```bash
git describe --tags --abbrev=0
```

### Step 2: Collect Merged PRs

```bash
gh pr list --state merged --search "merged:>$(git log -1 --format=%cI $(git describe --tags --abbrev=0))"
```

### Step 3: Group and Draft

Group the pull requests by change type:
- **Features**: new commands, flags, or rules
- **Fixes**: bug fixes with the issue number in parentheses
- **Docs**: documentation-only changes

Write one bullet per pull request, in the imperative mood, and open the
draft in the editor for review.
