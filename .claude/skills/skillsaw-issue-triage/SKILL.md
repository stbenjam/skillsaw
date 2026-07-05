---
name: skillsaw-issue-triage
description: Triage a GitHub issue filed against skillsaw — classify it (bug, feature, docs, question, other), verify its claims against the codebase, enrich it with missing details, and post one structured triage comment. Use to triage and label incoming issues, not to fix them.
compatibility: Requires git, gh CLI, and internet access
user-invocable: true
metadata:
  author: stbenjam
  version: "1.0"
---

# skillsaw Issue Review

Triage a single open issue on the **skillsaw** linter: decide what kind of
issue it is, check whether its claims hold up against the actual code, fill in
the details it is missing, and leave one clear triage comment. This skill
**reviews** issues — it does not fix them (that is `skillsaw-issue-solver`).

Each classification has a detailed evaluation checklist in `references/`,
loaded **only for the class the issue falls into** (progressive disclosure).
Keep this file lean and pull the checklist in on demand.

## Step 1 — Read the Issue

Given an issue number:

```bash
gh issue view <number> --json number,title,body,labels,author,comments,createdAt
```

Read the title, body, and every comment before judging anything. Note the
skillsaw version the reporter names (or that they named none) and any config,
command, or file content they pasted.

## Step 2 — Classify

Assign exactly one primary class. When an issue spans two, pick the one that
determines the next action and note the secondary in the comment.

| Class | The issue is… | Evaluation checklist |
|---|---|---|
| `bug` | A claim that skillsaw behaves incorrectly — wrong violation, crash, false positive/negative, bad autofix | `references/bug-evaluation.md` |
| `feature` | A request for new behavior — a new rule, flag, config option, output format, or tool/format support | `references/feature-evaluation.md` |
| `documentation` | Docs are missing, wrong, or unclear (README, skillsaw.org, rule docs) — code behavior is not disputed | `references/other-evaluation.md` |
| `question` | A usage/support question, not a defect or request | `references/other-evaluation.md` |
| `other` | Duplicate, invalid, spam, out-of-scope, or needs-more-info | `references/other-evaluation.md` |

State the class and a one-sentence rationale.

## Step 3 — Evaluate Accuracy

**Read the checklist for the chosen class now** (`references/*.md`) and work it.
The goal is to decide whether the issue is *accurate* — do its claims match how
skillsaw actually behaves?

- For a **bug**: attempt to reproduce against the current code. Trace the cited
  behavior to the rule/module responsible. A bug that cannot be reproduced, or
  that describes intended behavior, is not confirmed — say so with evidence.
- For a **feature**: check whether it already exists, whether it fits skillsaw's
  scope (core vs a rule plugin — see the ecosystem boundary), and whether it
  would break existing users.
- For **documentation / question / other**: verify the underlying facts before
  agreeing or redirecting.

Cite what you checked with `file:line` references and command output. Never
assert a conclusion you did not verify.

## Step 4 — Enrich

Add the details the issue is missing so it is actionable without a round-trip:

- **Reproduction**: a minimal repro (config + input file + command + observed vs
  expected) when the reporter left one out and you were able to construct one.
- **Locus**: the rule ID, file, and line most relevant to the issue.
- **Version / environment**: the version the behavior was verified against, and
  whether it still reproduces on `main`.
- **Related work**: link duplicate or related issues and any open PR that already
  touches this (`gh issue list` / `gh pr list --search`).
- **Suggested labels**: propose labels (e.g. `bug`, `enhancement`, `documentation`,
  `question`, `duplicate`, `needs-info`, `good-first-issue`) — do not apply them
  unless asked.

## Step 5 — Post One Triage Comment

Render `references/triage-template.md` and post it as exactly ONE comment:

```bash
gh issue comment <number> --body "$(cat <<'TRIAGE'
<rendered triage>
TRIAGE
)"
```

Do not close, label, or reassign the issue unless the user explicitly asks —
this skill is advisory. Its output is a recommendation for a maintainer.
