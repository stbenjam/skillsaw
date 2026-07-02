## Why

Claude Code validates agent frontmatter against a documented set of
fields and values. Enum fields like `permissionMode`, `memory`,
`effort`, `isolation`, and `color` only take specific values — a typo
such as `isolation: sandbox` is silently ignored rather than failing
loudly, so the agent quietly runs without the behavior you asked for.
Plugin-shipped agents additionally do not support `hooks`,
`mcpServers`, or `permissionMode` for security reasons; Claude Code
ignores those fields, which is a real footgun when a plugin author
expects them to apply.

## Examples

**Bad:**

```yaml
---
name: db-reviewer
description: Reviews database migrations
memory: global
color: teal
---
```

**Good:**

```yaml
---
name: db-reviewer
description: Reviews database migrations
memory: project
color: cyan
---
```

## How to fix

Replace the flagged value with one of the documented values listed in
the violation message. For plugin-shipped agents, remove `hooks`,
`mcpServers`, and `permissionMode` from the frontmatter — they only
work on project agents in `.claude/agents/`.
