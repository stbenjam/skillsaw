## Why

A skill's YAML frontmatter is its public interface: the `name` and
`description` fields are what an agent reads when deciding whether to
load the skill. A SKILL.md without frontmatter — or without those two
fields — is invisible to skill discovery, so the content below it never
gets used no matter how good it is.

## Examples

**Bad:**

```markdown
# My deployment skill

Use this when deploying to staging...
```

**Good:**

```markdown
---
name: deploy-staging
description: Deploy the application to the staging environment. Use when
  the user asks to deploy, ship, or release to staging.
---

# My deployment skill
...
```

## How to fix

Add a frontmatter block with `name` (lowercase, hyphenated, matching the
skill's directory name) and `description` (third person, stating both
what the skill does and when to use it). Related rules validate the
details: `agentskill-name` checks the name format and
`agentskill-description` checks description quality.
