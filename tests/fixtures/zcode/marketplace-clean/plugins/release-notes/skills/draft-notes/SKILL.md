---
name: draft-notes
description: Groups merged pull requests by label and drafts release notes. Use when preparing a release or updating CHANGELOG.md.
---

# Drafting release notes

1. Find the previous tag with `git describe --tags --abbrev=0`.
2. List merged pull requests since that tag.
3. Group them under Features, Fixes and Maintenance.
4. Write one line per pull request, linking its number.
