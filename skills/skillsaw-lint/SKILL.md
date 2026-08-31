---
name: skillsaw-lint
description: "Use when modifying agentic contextual building blocks like skills (SKILL.md), slash commands, agents, hooks, plugins, marketplaces, and instruction files (CLAUDE.md, AGENTS.md, GEMINI.md, QWEN.md, Cursor, Copilot, Cline, or Kiro rules), and tool configuration such as an OpenCode `opencode.json`. Run skillsaw on the files you touched, apply autofixes, resolve remaining violations with `skillsaw explain` guidance, and re-lint until clean before considering the work complete."
compatibility: "Requires skillsaw CLI. Check the project's Makefile, pyproject.toml, or .venv for the pinned version before installing."
license: Apache-2.0
metadata:
  author: stbenjam
  version: "1.0"
---

# skillsaw Lint

You just authored or edited agentic context — a skill, slash command, agent,
hook, plugin, marketplace, or instruction file (CLAUDE.md, AGENTS.md,
GEMINI.md, Cursor/Copilot/Cline/Kiro rules), or the configuration that
loads it (an OpenCode `opencode.json`). That content feeds an agent's
context window, and defects in it — weak language, contradictions,
placeholder text, instructions buried in attention dead zones — degrade
every future session that loads it. Lint it with **skillsaw** and improve
it before you report the work as done.

Run the skillsaw CLI for every step below; it is the interface for linting,
fixing, and explaining — replace any hand-rolled check with it.

## Step 1: Locate skillsaw

Run `skillsaw --version`. If the command is missing, check the project for a
pinned version before installing — look in the Makefile, pyproject.toml, or
an existing `.venv` (e.g. `.venv/bin/skillsaw --version`). Use that version
with `uvx skillsaw==<version>` as the prefix for every command below (or
`pip install skillsaw==<version>` if uvx is unavailable).

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
and similar) for errors and warnings. When the lint output reports fixable
info-level findings, add `--severity info` to each fix command in this step.
Run `skillsaw fix --dry-run` first to inspect the diff before anything is
written. For the second tier of mechanically derived fixes (stale-reference
updates after a rename, for example), run `skillsaw fix --suggest --dry-run`
and review each hunk; if every hunk is correct, run `skillsaw fix --suggest`
to apply them.

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
