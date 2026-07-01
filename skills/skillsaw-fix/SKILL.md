---
name: skillsaw-fix
description: "Fix skillsaw lint violations — apply deterministic autofixes, then resolve the remaining violations with targeted edits guided by `skillsaw explain`. Use when skillsaw reports violations, when asked to clean up lint findings, or after `skillsaw fix` leaves violations behind."
compatibility: "Requires skillsaw (uvx skillsaw or pip install skillsaw)."
metadata:
  author: stbenjam
  version: "1.0"
---

# skillsaw Fix

You are fixing **skillsaw** lint violations in this repository. skillsaw lints
agentic contextual building blocks (CLAUDE.md, skills, plugins, agents, hooks,
etc.). Deterministic fixes are applied by the tool itself; everything else is
your job — you read the violation, load the rule's how-to-fix guidance, and
make a targeted edit.

Work through the steps in order. Report progress to the user at each stage.

## Step 1: Locate skillsaw

Run `skillsaw --version`. If the command is missing, use `uvx skillsaw` as the
prefix for every command below (or `pip install skillsaw` if uvx is
unavailable).

## Step 2: Lint and inventory

Run `skillsaw` (lint) from the repository root and capture the output. Each
violation line includes the severity, file path, line number, message, and
rule ID.

If the lint exits 0 with no violations, tell the user the repository is clean
and stop.

Build an inventory: group the violations by rule ID and note how many files
each rule touches. Show the user this summary before making changes.

## Step 3: Apply deterministic autofixes

Run `skillsaw fix`. This applies safe, structural fixes (missing frontmatter,
kebab-case names, plugin registration, and similar).

Then preview the suggested tier with `skillsaw fix --suggest --dry-run`.
Suggested fixes (e.g. updating stale references after a rename) are
mechanically derived but may over-match. Review the diff output; if the
changes are correct, apply them with `skillsaw fix --suggest`. If any look
wrong, skip this tier and handle those violations manually in Step 5.

Re-run `skillsaw` and report how many violations the autofixer resolved.

## Step 4: Load fix guidance for each remaining rule

For every rule ID still in the inventory, run:

```
skillsaw explain <rule-id>
```

The output includes the rule's rationale and a "How to fix" section — this is
the authoritative guidance for what a correct fix looks like. Read it before
editing anything. Do not guess at what a rule wants from its message alone.

## Step 5: Fix the remaining violations

Work file by file. For each violation:

1. Read the file and understand the context around the flagged line
2. Apply the `skillsaw explain` guidance with a targeted edit — change only
   the text that triggers the violation, preserving the author's meaning,
   structure, and formatting
3. Keep edits minimal — never rewrite a whole file to fix one line

After finishing a file, re-run `skillsaw` scoped to confirm the violations
are gone and your edit introduced no new ones.

Common cases:

<!-- skillsaw-disable content-weak-language, content-tautological -->
- **content-weak-language**: replace hedges ("try to", "consider", "if
  possible") with direct imperatives or explicit conditions.
- **content-tautological**: delete empty truisms ("follow best practices") or
  replace them with the specific, actionable instruction the author meant.
<!-- skillsaw-enable content-weak-language, content-tautological -->
- **content-negative-only**: keep the prohibition, add what to do instead.
- **Missing or invalid frontmatter fields**: derive names from directory
  names and descriptions from the body content.
- **content-embedded-secrets**: replace the secret with an environment
  variable placeholder and tell the user to rotate the credential — removing
  it from the file does not remove it from git history.

## Step 6: Escalate what you cannot decide

Some violations need decisions only the user can make — for example, which of
two contradictory instructions is correct, or whether a flagged reference is
intentional. Do not invent an answer. List these violations with your
recommendation and ask the user.

If the user wants to accept some violations for now, run `skillsaw baseline`
so only new violations fail future lints, and remind them to commit
`.skillsaw-baseline.json`.

## Step 7: Verify and summarize

Run `skillsaw` one final time. Report:

- Violations fixed automatically (Step 3)
- Violations fixed by edits (Step 5)
- Violations escalated or baselined (Step 6)
- Files modified
- Final exit status

If the lint still fails, show the remaining violations and explain why each
one is still open.
