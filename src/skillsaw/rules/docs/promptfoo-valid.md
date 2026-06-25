## Why

Promptfoo eval YAML configs define test suites for skills and plugins.
Invalid YAML, missing required fields, or broken file references mean
evals cannot run — regressions in skill behavior go undetected.

## Examples

**Bad:**

```yaml
prompts:
  - file://nonexistent.txt
```

**Good:**

```yaml
prompts:
  - file://../../SKILL.md
tests:
  - vars:
      input: "deploy to staging"
    assert:
      - type: contains
        value: "deployed"
```

## How to fix

Fix the YAML syntax or structural issue identified in the violation.
Ensure `prompts` and `tests` arrays exist, file references point to
real files, and the overall structure matches the promptfoo config
schema.
