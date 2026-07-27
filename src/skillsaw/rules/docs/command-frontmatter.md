## Why

Command files need YAML frontmatter with a `description` field so the
host application can display help text and decide when to offer the
command. Without it, the command exists but is undiscoverable.

## Examples

**Bad:**

```markdown
## Name

my-plugin:deploy

## Description
...
```

**Good:**

```markdown
---
description: Deploy the application to production
---

## Name

my-plugin:deploy
...
```

## How to fix

Add a YAML frontmatter block at the top of the command file with a
`description` field. `skillsaw fix` can add the missing frontmatter
automatically.

## Codex plugins

This is a Claude-format convention. A directory claimed only by OpenAI
Codex — a `.codex-plugin/plugin.json`, or a local-source listing in a
Codex catalog, with no `.claude-plugin` marker or Claude marketplace
listing — is exempt: Claude never loads it, so Claude command frontmatter requirements do not apply to its commands/. A dual-manifest
directory keeps this check, and the ecosystem-neutral content and
security rules read every plugin's files regardless of provenance.
