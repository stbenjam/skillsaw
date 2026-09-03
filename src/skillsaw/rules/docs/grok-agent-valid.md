## Why

A `.grok/agents/*.md` file is a Grok Build subagent: prose the model is
handed when it delegates, plus the frontmatter Grok registers it by. That
frontmatter needs a `name` and a `description`. Without either, Grok drops
the file and says nothing — the agent is committed, reviewed, and simply
never appears in the agent list. From the outside that is
indistinguishable from an agent the model had no reason to pick, which is
why the mistake survives review.

The `description` is also what routes the subagent: it is the text the model
reads when deciding whether to delegate. Whether the description that *is*
there says when to use the agent is
[`content-description-routing`](content-description-routing.md)'s question;
this rule only asks whether Grok will load the file at all.

`.grok/commands/*.md` is deliberately not checked. Grok loads a command with
no frontmatter, naming it from the filename, so requiring any there would
report a file that works.

## Severity

**Error** — Grok does not register the subagent.

- Frontmatter that is not valid YAML.
- No frontmatter block at all.
- No `name` key.
- No `description` key.

Presence is the whole test. An empty value satisfies Grok — an agent
carrying `description: ""` still registers — so an empty description is
not reported here.

## Examples

**Bad** — a subagent Grok never loads, because the frontmatter names it and
stops:

```markdown
---
name: migration-reviewer
---

# Migration reviewer

Read the migration and report anything the schema diff does not explain.
```

**Good** — both keys present, so the agent registers and the model has
something to route on:

```markdown
---
name: migration-reviewer
description: Use when reviewing a database migration, to check that it is forward-only and matched by the code that reads the new columns.
tools: read_file, run_terminal_command
---

# Migration reviewer

Read the migration and report anything the schema diff does not explain.
```

## How to fix

- Give every `.grok/agents/*.md` a frontmatter block with `name` and
  `description`.
- Write the `description` as the condition for delegating to the agent
  ("Use when ..."), not as a restatement of its name — that is what the
  model reads to choose it.
- Keys Grok does not require, such as `tools` and `model`, are fine to keep.
