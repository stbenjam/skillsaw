## Why

Agent `.md` files need YAML frontmatter with `name` and `description`
so that the host application can discover and register them. Without
frontmatter, the agent file is invisible to the runtime — its
instructions will never be loaded.

## Examples

**Bad:**

```markdown
# Code reviewer

Review pull requests for correctness and style...
```

**Good:**

```markdown
---
name: code-reviewer
description: Review pull requests for correctness and style issues.
  Use when the user asks to review a PR or diff.
---

# Code reviewer

Review pull requests for correctness and style...
```

## How to fix

Add a YAML frontmatter block with `name` (matching the filename stem)
and `description` (imperative, stating what the agent does and when to
invoke it). `skillsaw fix` can add missing frontmatter fields
automatically.
