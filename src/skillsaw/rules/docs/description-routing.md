# description-routing

Checks that skill, agent, and command descriptions work as routing signals rather than labels or documentation fragments.

## What it checks

- Skill and agent descriptions say when the model should use them. Commands are excluded because users select them directly.
- Descriptions avoid first-person voice such as "I can help" or "I'll".
- Descriptions do more than restate the building block name, such as a `deploy-staging` skill described only as "Deploy staging."

Each check can be configured independently:

```yaml
rules:
  description-routing:
    require-trigger-phrasing: true
    flag-first-person: true
    flag-name-restatement: true
```

## Why this matters

Descriptions are the text a model uses to decide which skill or agent should handle a request. A description that gives no usage trigger, speaks as the tool, or repeats only its name provides little evidence for that decision.

## How to fix

State what the building block does and the situations or user phrases that should route to it. Use direct or third-person language. For example: "Deploys the current build to staging. Use when the user asks to test a change in the staging environment."

This rule reports warnings and does not autofix prose.
