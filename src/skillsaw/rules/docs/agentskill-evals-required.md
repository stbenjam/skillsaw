## Why

Skills without evals have no automated way to verify they still work
after changes. This opt-in rule enforces that every skill directory
includes an `evals/evals.json` file, ensuring eval coverage is a
gating requirement.

## Examples

**Bad:**

```
my-skill/
  SKILL.md
```

**Good:**

```
my-skill/
  SKILL.md
  evals/
    evals.json
```

## How to fix

Create an `evals/evals.json` file inside the skill directory with at
least one test case covering the skill's primary use case. This rule
is disabled by default — enable it in your config when you want to
enforce eval coverage:

```yaml
rules:
  agentskill-evals-required:
    enabled: true
```
