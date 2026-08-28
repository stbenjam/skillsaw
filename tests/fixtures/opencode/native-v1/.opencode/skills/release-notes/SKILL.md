---
name: release-notes
description: Assemble release notes for a billing-api tag from merged pull requests. Use when cutting a release or when asked what shipped in a version.
---

# Release notes

Assemble the notes for one tag from the pull requests merged since the
previous tag.

## Gather the changes

1. Find the previous tag with `git describe --tags --abbrev=0 HEAD^`.
2. List the merges with `git log --merges --pretty=%s <previous>..HEAD`.
3. For each merge, read the pull request body with
   `gh pr view <number> --json title,body`.

## Write the notes

Group the entries under three headings, in this order: `Added`, `Changed`,
`Fixed`. Drop a heading with no entries rather than writing "none".

Write each entry as one sentence in the past tense, naming the behaviour a
user sees rather than the code that changed. Append the issue key in
parentheses.

## Finish

Write the result to `docs/releases/<tag>.md` and stop. Do not tag, commit,
or publish anything.
