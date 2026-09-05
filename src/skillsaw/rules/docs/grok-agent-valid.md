## Why

In Grok Build, custom project subagents live in `.grok/agents/*.md`. These
markdown files provide specialized instructions that the model delegates to
during multi-step workflows.

To register a subagent and make it available in the agent list, Grok Build
requires two YAML frontmatter fields: `name` and `description`. If either
field is omitted, Grok skips registering the subagent during session startup,
so it won't appear in the list of available agents.

The `description` also helps the model decide when to delegate tasks to the
subagent. While [`content-description-routing`](content-description-routing.md)
evaluates whether the description provides clear routing context, this rule
verifies that the required frontmatter fields exist and have scalar values.
Grok accepts leading whitespace before the opening `---` and delimiter-line
suffixes such as `--- # Agent metadata`. Their YAML fields and body retain
file-relative locations for lint findings.

Slash commands in `.grok/commands/*.md` do not require frontmatter; Grok
automatically derives command names from their filenames.

## Severity

**Error** — Grok does not register the subagent without required frontmatter:

- Frontmatter that is not valid YAML.
- Missing YAML frontmatter block.
- Missing `name` key.
- Missing `description` key.
- A sequence or mapping in either required field.

Both keys must be present. Grok converts YAML scalars to strings here, including
numbers, booleans, null and empty values. A list or mapping is rejected even
when it contains a single string. Description quality and guidance are checked
separately by [`content-description-routing`](content-description-routing.md).
This rule does not validate every optional field accepted by the agent decoder.

## Examples

**Bad** — missing `description`, so Grok skips registering the agent:

```markdown
---
name: migration-reviewer
---

# Migration reviewer

Read the migration and report anything the schema diff does not explain.
```

**Good** — includes both `name` and `description` so the agent registers cleanly:

```markdown
---
name: migration-reviewer
description: Use when reviewing a database migration to check that it is forward-only and matches the code reading new columns.
tools: read_file, run_terminal_command
---

# Migration reviewer

Read the migration and report anything the schema diff does not explain.
```

## How to fix

- Add a YAML frontmatter block containing both `name` and `description` to
  each agent file under `.grok/agents/*.md`.
- Replace a list or mapping in `name` or `description` with a scalar value.
  Descriptions spanning several lines can use YAML `|` or `>` block scalars.
- Phrase the `description` with actionable guidance on when the model should
  delegate to this agent (e.g., "Use when ...").
- Optional metadata fields like `tools` and `model` are welcome and can be
  kept in frontmatter alongside `name` and `description`.
