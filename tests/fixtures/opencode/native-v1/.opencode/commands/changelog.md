---
description: Draft the changelog entry for the current branch
agent: reviewer
---

Read the commits on this branch with `git log --oneline main..HEAD`.

Write one changelog entry per user-visible change, in the past tense, and
append them under the `## Unreleased` heading in `CHANGELOG.md`.

Skip commits that only touch tests, CI configuration, or formatting. Stop
after appending the entries; do not commit or push.
