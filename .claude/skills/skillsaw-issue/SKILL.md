---
name: skillsaw-issue
description: "Use when skillsaw reports a likely false positive, misses an edge case, behaves incorrectly, or needs an RFE. Gather a safe report and, only with explicit user permission, create a feedback bundle or open a GitHub issue."
compatibility: "Requires skillsaw; gh CLI is optional for an approved GitHub issue."
license: Apache-2.0
metadata:
  author: stbenjam
  version: "1.0"
---

# skillsaw Issue

Use this skill when skillsaw itself needs a GitHub issue: a false positive, a
missed violation, a crash, incorrect autofix, an edge case in rule detection,
or a request for enhancement (RFE). Do not use it to report a problem in the
repository being linted unless that problem demonstrates incorrect skillsaw
behavior or a useful feature gap.

## Gather safe evidence first

Collect the minimum evidence needed to explain the issue without sending
anything externally:

- skillsaw version and the exact command
- affected rule ID, file type, and relevant configuration
- expected behavior and actual behavior for a bug
- user goal and proposed outcome for an RFE
- a minimal reproducer or a short sanitized excerpt

Never copy credentials, private repository content, or complete diagnostic
output into an issue draft. Prefer a minimal synthetic reproducer.

## Require separate permission for each external action

Ask the user two explicit questions before taking either action:

1. "May I run `skillsaw feedback` to create a local diagnostic ZIP?"
2. "May I open an issue in `stbenjam/skillsaw`?"

Do not run `skillsaw feedback` without permission for the first action. Do
not create a GitHub issue without permission for the second action. Permission
for one action does not authorize the other. If permission is absent, present
a sanitized draft and ask for the missing approval.

## Create a feedback bundle only when approved

Run `skillsaw feedback <repository-path>` with a concise `--message` that
describes the observed behavior. The command creates a local ZIP; it does not
submit anything. Do not add `--include` unless the user explicitly identifies
the file to share.

Review the ZIP before sharing it. Its redaction is best effort, so remove or
replace anything sensitive. Keep the bundle local if the user does not also
approve opening an issue.

## Open an issue only when approved

Search existing issues first to avoid duplicates. Then open an issue in
`stbenjam/skillsaw` with:

- a specific title naming the affected rule, behavior, or requested capability
- the minimal reproducer and exact command for a bug
- expected and actual results for a bug, or the user goal and proposed outcome for an RFE
- skillsaw version and relevant configuration when applicable
- the reviewed feedback ZIP only when the user approves attaching it

State which sensitive details were omitted. Link the issue back to the user
and summarize what was shared. Do not change labels, milestones, assignees, or
project state unless the user specifically requests it.
