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

## Choosing a tighter budget

The length limit defaults to the agentskills.io spec's 1024
characters, so default behavior matches the spec. It is configurable
via `max_length`, and a tighter budget is recommended: the
description is permanent context, loaded into every prompt so the
agent can decide which skill to route to, meaning every character is
paid on every request — and some ecosystems rank or route on only a
prefix of the description. `256` is a good working budget:

```yaml
rules:
  agentskill-description:
    max_length: 256
```

Values above 1024 are honored as configured; the spec's own limit is
enforced by the ecosystem at publish time.
