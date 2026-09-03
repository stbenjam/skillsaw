---
name: skillsaw-update
description: "Update a repository to the newest skillsaw — upgrade the install, report new rules and their findings in your repo, and bump version pins (GitHub Action SHAs, Makefile targets, pre-commit hooks). Use when a new skillsaw release is out and you want its latest checks."
compatibility: "Requires skillsaw already adopted (uvx skillsaw, pip install skillsaw, or container). Network access for version lookup."
license: Apache-2.0
user-invocable: true
disable-model-invocation: true
metadata:
  author: stbenjam
  version: "1.0"
---

# skillsaw Update

Update this repository from its installed skillsaw to the newest release:
upgrade the local install, report which rules are new and what they find in
this repository, and bump every pinned skillsaw version (GitHub Actions
SHAs, Makefile targets, pre-commit hooks, container tags).

## Workflow

Ask one routing question at a time and wait for the answer. An explicit choice
in the user's request already counts as an answer. Read a reference only after
its condition or a yes answer routes to it; do not read the reference to
formulate the question. After completing it, return here. If the answer is no,
continue to the next checkpoint without reading it. Carry forward the command
prefixes, versions, rule lists, and changed-file list.

Resolve every `references/...` path relative to the directory containing this
`SKILL.md`, never relative to the target repository or the process's current
working directory. If this file was fetched from the web, resolve each
reference against the parent URL of this file and fetch it from that sibling
location.

Replace brace-delimited fields below with facts from the repository or scan;
never show placeholders to the user, and render singular or plural wording
naturally.

### 1. Upgrade to the newest version

Read [versions](references/01-versions.md). It records the installed and
latest versions, captures the old rule list, upgrades the install (or selects
the new command prefix), and verifies the result. Report both versions before
offering changes.

### 2. Report new rules

Read [new rules](references/02-new-rules.md). It diffs the old and new rule
lists, explains each added rule, and scans the repository with the new
version so every new rule is presented with its actual findings here.

### 3. Update version pins

If the repository pins skillsaw anywhere (GitHub Actions workflows, Makefile
targets, pre-commit hooks, container image tags), ask:

> I found skillsaw pinned in {locations}. Bumping them to {latest} keeps CI
> and local runs on the version just installed. Should I update those pins?

If yes, read [pins](references/03-pins.md). If no, preserve the locations.

### 4. Triage findings from new rules

If the new version reports findings from added rules, read
[triage](references/04-triage.md) and present its summary table for
confirmation before making changes. Carry the agreed buckets forward.

### 5. Verify the result

After all accepted routes finish, always read
[verification](references/05-verify.md).
