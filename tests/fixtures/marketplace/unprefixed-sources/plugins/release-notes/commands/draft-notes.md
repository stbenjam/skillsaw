---
description: Draft release notes for the commits since the last tag
argument-hint: "[since-tag]"
---

## Steps

1. Find the most recent release tag with `git describe --tags --abbrev=0`, or use $ARGUMENTS when given.
2. List the merged pull requests since that tag with `git log --merges --oneline <tag>..HEAD`.
3. Draft release notes for the commits since the last tag, and report anything you could not resolve.
