---
name: skillsaw-fix
description: "Fix skillsaw lint violations — apply deterministic autofixes, then resolve the remaining violations with targeted edits guided by `skillsaw explain`. Use when skillsaw reports violations, when asked to clean up lint findings, or after `skillsaw fix` leaves violations behind."
compatibility: "Requires skillsaw (uvx skillsaw or pip install skillsaw)."
license: Apache-2.0
metadata:
  author: stbenjam
  version: "1.0"
---

# skillsaw Fix

Review and fix **skillsaw** lint violations in this repo. skillsaw lints agentic
contextual building blocks (CLAUDE.md, skills, plugins, agents, hooks,
etc.). The tool applies deterministic fixes itself; handle everything else
yourself — read the violation, load the rule's how-to-fix guidance, and
make a targeted edit.

Follow the steps in order. Report progress to the user at each stage.

## Step 1: Install and locate skillsaw

Run `skillsaw --version`. If the command is missing, use `uvx skillsaw` as the
prefix for every command below (or `pip install skillsaw` if uvx is
unavailable).

## Step 2: Run the lint and build an inventory

Run `skillsaw` (lint) from the repo root and capture the output. Each
violation line includes the severity, file path, line number, message, and
rule ID — read them all.

If the lint exits 0 with no violations, tell the user the repo is clean and stop.

Build an inventory: group the violations by rule ID and check how many files
each rule touches. Review this summary with the user before making changes.

## Step 3: Run deterministic autofixes

Run `skillsaw fix`. This applies safe, structural fixes (missing frontmatter, kebab-case names, plugin registration, and similar).

Then run `skillsaw fix --suggest --dry-run` to preview the suggested tier.
Suggested fixes (e.g. updating stale references after a rename) are
mechanically derived but may over-match, so review each hunk in the diff
individually: for a stale-reference rewrite, check whether the flagged text
is really a reference to the skill or just the same word used generically —
"the `data-parser` skill" is a reference; "our data parser" is not. If every
hunk is correct, run `skillsaw fix --suggest` to apply the tier. If any hunk is
wrong, skip the tier entirely, handle those violations manually in Step 5, and
keep only the edits you judged correct.

Re-run `skillsaw` and report how many violations the autofixer resolved.

## Step 4: Read fix guidance for each remaining rule

For every rule ID still in the inventory, run:

```sh
skillsaw explain <rule-id>
```

Read the rule's rationale and its "How to fix" section from the output — this is
the authoritative guidance for what a correct fix looks like. Read it before
editing anything. Never guess at what a rule wants from its message alone.

## Step 5: Review and fix the remaining violations

Handle the violations file by file. For each violation:

1. Read the file and understand the context around the flagged line
2. Follow the `skillsaw explain` guidance with a targeted edit — change only
   the text that triggers the violation, and keep the author's meaning,
   structure, and formatting
3. Keep edits minimal — never rewrite a whole file to fix one line

After finishing a file, re-run `skillsaw` scoped to confirm the violations
are gone and your edit introduced no new ones. Always re-lint even after an edit
that looks obviously correct: wrap a path in a link, split a section,
or add a directive, and you can trip a *different* rule you now have to fix.

### Handle common cases

<!-- skillsaw-disable content-weak-language, content-tautological -->
- **content-weak-language**: remove hedges ("try to", "consider", "if
  possible") — use direct imperatives or explicit conditions instead.
- **content-tautological**: delete empty truisms ("follow best practices"), or
  write the specific, actionable instruction the author meant instead.
<!-- skillsaw-enable content-weak-language, content-tautological -->
- **content-negative-only**: keep the prohibition, add what to do instead.
- **content-unlinked-internal-reference**: wrap the path in `[path](path)`
  **only when it resolves relative to the flagged file's own directory**.
  Links resolve from the file, not the repo root — so never link a repo-root path
  mentioned in a doc nested under a subdirectory, since it does NOT resolve
  from there and a link to it trips `content-broken-internal-reference` (a
  warning, strictly worse than the info you started with). Keep those bare
  and suppress the rule instead (see "Suppressing violations you cannot fix
  in content"). Verify a path exists before you link it — never link stale paths that become broken links.
- **agentskill-rename-refs**: single-word skill names are flagged but never
  rewritten automatically — the word is too ambiguous. Check each flagged
  line yourself: rewrite it only if the mention actually refers to the skill
  (`/name` invocations, `skills/name/` paths, "the name skill"), and keep
  generic uses of the word unchanged.
- **Missing or invalid frontmatter fields**: derive names from directory
  names, and write descriptions from the body content.
- **content-embedded-secrets**: replace the secret with an environment
  variable placeholder, and always tell the user to rotate the credential — removing
  it from the file does not remove it from git history.

### Handle violations you cannot fix in content

Some violations are correct signal but the flagged text is deliberate — a
repo-root reference that must stay bare, a template that is intentionally
terse, prose where a term is idiomatic. Keep the content and suppress the rule
instead of distorting it. Which mechanism you use depends on whether the
violation carries a **line number**.

**Line-numbered violations** — use an inline HTML comment directive to suppress them:

```markdown
<!-- skillsaw-disable-next-line rule-id -->
the flagged line

<!-- skillsaw-disable rule-id -->
...a flagged region...
<!-- skillsaw-enable rule-id -->
```

Avoid three syntax traps that make directives silently misfire:

- Keep the directive comment to **only** `skillsaw-disable <rule-ids>`. Never
  add trailing prose (`skillsaw-disable rule-id — because ...`) — it fails the
  match and the directive does nothing. Keep human rationale in a *separate* comment.
- Use `disable-next-line` for **exactly one** following line. If the flagged
  path or phrase sits on the second line of a wrapped sentence, merge it onto
  the directive's target line or use a `disable`/`enable` block instead.
- Never place a comment between list items or inside a paragraph — it **splits
  the markdown** into separate blocks. Keep block `disable`/`enable` markers
  *outside* the list or paragraph, or keep the flagged text on one line.

**File-level violations (no line number)** — some rules always score the whole file
and never report a line: e.g. `content-actionability-score` and
`content-inconsistent-terminology`. Inline directives **cannot** suppress
these — a `<!-- skillsaw-disable -->` comment has no effect on them. Use
config in `.skillsaw.yaml` instead:

```yaml
rules:
  content-actionability-score:
    # Scoped per-rule exclude — keeps the rule enforced everywhere else
    exclude: ["**/references/**", "REVIEW.md"]
  content-inconsistent-terminology:
    # Disable only a group that legitimately does not apply
    groups:
      function/method: off
```

Prefer a scoped per-rule `exclude` over disabling the rule globally, so the
rule keeps working where it belongs. Always escalate or baseline (Step 6) when
even that is too broad, or the call is the maintainer's to make.

## Step 6: Escalate decisions only the user can make

Some violations need decisions only the user can make — for example, which of
two contradictory instructions is correct, or whether a flagged reference is
intentional. Never invent an answer. List these violations with your
recommendation, and ask the user.

If the user wants to accept some violations for now, run `skillsaw baseline`
so only new violations fail future lints, and remind them to commit `.skillsaw-baseline.json`.

## Step 7: Verify and summarize

Run the repo's own lint entry point if it defines one — check the Makefile
(or equivalent task runner) for a skillsaw target such as `lint` or
`lint-fix` and use that, since it may pin a version or pass flags like
`--strict`. Otherwise run `skillsaw` directly.

Check whether the repo has a grade badge (`.skillsaw-badge.json` exists, or the
lint target depends on a `badge` target), refresh it: run `make badge` if
defined, else run `skillsaw badge`. The badge reflects committed state, so
include the updated `.skillsaw-badge.json` in the files to commit.

Review and report:

- Violations fixed automatically (Step 3)
- Violations fixed by edits (Step 5)
- Violations escalated or baselined (Step 6)
- Files modified
- Final exit status

If the lint still fails, always show the remaining violations and explain why each one is still open.
