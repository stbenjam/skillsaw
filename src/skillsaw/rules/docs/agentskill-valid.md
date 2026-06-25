## Why

A SKILL.md file is the entry point for skill discovery. Without valid
YAML frontmatter containing `name` and `description`, the skill cannot
be found or loaded by the host application — the body content is
effectively dead.

## Examples

**Bad:**

```markdown
Deploy the application to staging.
```

**Good:**

```markdown
---
name: deploy-staging
description: Deploy the application to the staging environment. Use
  when the user asks to deploy or ship to staging.
---

Deploy the application to staging.
```

## How to fix

Add a YAML frontmatter block between `---` delimiters at the top of
SKILL.md with at least `name` and `description` fields. If the
frontmatter exists but is malformed, fix the YAML syntax errors
reported in the violation message. `skillsaw fix` can add missing
fields automatically.
