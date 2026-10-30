---
name: release-notes
description: Draft release notes from a supplied commit range and issue list. Use when preparing a release announcement or summarizing changes for users.
license: Apache-2.0
---

# Draft release notes

Read the supplied commit range and linked issues. If the release version or
comparison range is missing, ask the user for that information before drafting.

Group the changes into features, fixes, and upgrade steps. Describe the effect
on users and link each entry to its supporting commit or issue. Omit empty
groups and flag changes that lack enough evidence to describe accurately.

Check the draft against the [release checklist](references/checklist.md).
Return the Markdown draft and a list of unresolved questions for the publisher.
