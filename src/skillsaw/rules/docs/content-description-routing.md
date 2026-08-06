Checks that skill and agent descriptions work as routing signals, while command descriptions clearly explain their picker-visible purpose.

## What it checks

- Descriptions are present, non-empty strings. This basic check stays on when the routing heuristics are disabled.
- Skill and agent descriptions say when the model should use them. Commands are excluded because users select them directly.
- Descriptions do more than restate the building block name or category, such as a `deploy-staging` skill described only as "Deploy staging" or a command described only as "A command."

Skills with `disable-model-invocation: true` are user-only: the model cannot route
to them, so this rule skips them by default. Set `check-user-only-skills: true`
to check their descriptions normally. Only the YAML boolean `true` opts a skill
out; an absent field, `false`, strings, and numbers remain checked.

Natural selection clauses count as trigger phrasing, including "Use this skill
for ...", "Invoke this skill whenever ...", "This skill should be used before
...", and "Use only when ...".

The routing heuristics and user-only-skill behavior can be configured independently:

```yaml
rules:
  description-routing:
    require-trigger-phrasing: true
    flag-name-restatement: true
    check-user-only-skills: false
```

## Why this matters

Descriptions are the text a model uses to decide which skill or agent should handle a request. A description that gives no usage trigger or repeats only its name provides little evidence for that decision.

## How to fix

State what the building block does. For a skill or agent, also name the situations or user phrases that should route to it. Commands need a clear purpose but no routing phrase because users select them directly. For example: "Deploys the current build to staging. Use when the user asks to test a change in the staging environment."

This rule reports warnings and does not autofix prose.
