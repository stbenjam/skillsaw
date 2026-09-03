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
