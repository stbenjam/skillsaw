## Why

The skill description is what the agent reads to decide whether to
load the skill. A missing, empty, or overly long description means
the skill is either invisible or consumes excessive tokens in the
skill-selection prompt.

## Examples

**Bad:**

```yaml
---
name: deploy-staging
description: A skill.
---
```

**Good:**

```yaml
---
name: deploy-staging
description: Deploy the application to the staging environment. Use
  when the user asks to deploy, ship, or release to staging.
---
```

## How to fix

Write a description that states what the skill does and when to use
it. Keep it under 200 tokens — enough for the agent to make a
selection decision, not a full manual. Use imperative voice and
include trigger phrases the user might say.
