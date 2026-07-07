---
name: skillsaw-lint
description: "Lint and improve agentic context you just wrote — skills (SKILL.md), slash commands, agents, hooks, plugins, marketplaces, and instruction files (CLAUDE.md, AGENTS.md, GEMINI.md, Cursor, Copilot, Cline, or Kiro rules). Use whenever you author or modify any of these files, before considering the work complete: run skillsaw on the files you touched, apply autofixes, resolve remaining violations with `skillsaw explain` guidance, and re-lint until clean."
compatibility: "Requires skillsaw (uvx skillsaw or pip install skillsaw)."
license: Apache-2.0
metadata:
  author: stbenjam
  version: "1.0"
---

# skillsaw Lint

You just authored or edited agentic context — a skill, slash command, agent,
hook, plugin, marketplace, or instruction file (CLAUDE.md, AGENTS.md,
GEMINI.md, Cursor/Copilot/Cline/Kiro rules). That content feeds an agent's
context window, and defects in it — weak language, contradictions,
placeholder text, instructions buried in attention dead zones — degrade every
future session that loads it. Lint it with **skillsaw** and improve it before
you report the work as done.

Run the skillsaw CLI for every step below; it is the interface for linting,
fixing, and explaining — replace any hand-rolled check with it.

## Step 1: Locate skillsaw

Run `skillsaw --version`. If the command is missing, use `uvx skillsaw` as the
prefix for every command below (or `pip install skillsaw` if uvx is
unavailable).

## Step 2: Lint what you wrote

Run the linter scoped to the files or directories you created or edited:

```sh
skillsaw lint <path>
```

Read each violation line: it carries the severity, file path, line number,
message, and rule ID. If the repository defines its own lint entry point (a
Makefile `lint` target that runs skillsaw, for example), run that instead —
it may pin a version or pass flags like `--strict`.

If the lint exits 0 with no violations, your work is clean — stop here and
report done.

## Step 3: Apply deterministic autofixes

```sh
skillsaw fix <path>
```

This applies safe, structural fixes (missing frontmatter, kebab-case names,
and similar). Run `skillsaw fix --dry-run` first to inspect the diff before
anything is written. Run `skillsaw fix --suggest` for a second tier of
mechanically derived fixes (stale-reference updates after a rename, for
example) — review each hunk in that tier before applying it.

## Step 4: Resolve the remaining violations

For each rule ID still reported, load its guidance:

```sh
skillsaw explain <rule-id>
```

Read the rule's rationale and its "How to fix" section, then apply that
guidance with a targeted edit. Change only the text that triggers the
violation and keep the meaning you intended when you wrote it. Do not guess
a fix from the violation message alone; run `skillsaw explain` and follow
its guidance.

## Step 5: Re-lint until clean

Re-run `skillsaw lint <path>` after your edits and repeat Steps 3–4 until it
exits 0. Then run `skillsaw` from the repository root to confirm your changes
introduced no violations elsewhere. The lint output ends with a letter grade
for the repository's agentic content — leave it the same or better than you
found it.

## When to escalate

- **Many violations across many files**: hand off to the `skillsaw-fix`
  skill, which runs a deeper inventory, fix, and verify loop across a whole
  repository.
- **A violation that needs a decision only the user can make** (two
  contradictory instructions, a reference that looks stale but is
  intentional): present it to the user with your recommendation instead of
  inventing an answer.
