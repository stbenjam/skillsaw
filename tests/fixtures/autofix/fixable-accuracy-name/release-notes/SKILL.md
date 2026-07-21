---
name: Release_Notes
name: Release_Notes
description: Drafts release notes from the merged pull requests since the last tag. Use when preparing a new release.
---

# Draft release notes

Collect merged pull requests since the previous tag and group them by type.

1. List merges with `git log --merges <last-tag>..HEAD`.
2. Group entries under Features, Fixes, and Internal.
3. Write one user-facing sentence per entry.
