## Why

Eval tests without assertions pass unconditionally — they verify that
the skill runs without crashing but say nothing about whether the
output is correct. This opt-in rule enforces that every test case
includes specific assertion types you configure.

## Examples

**Bad:**

```yaml
tests:
  - vars:
      input: "deploy to staging"
```

**Good:**

```yaml
tests:
  - vars:
      input: "deploy to staging"
    assert:
      - type: contains
        value: "staging"
      - type: cost
        threshold: 0.05
```

## How to fix

Add assertion objects to each test case. Configure which assertion
types are required:

```yaml
rules:
  promptfoo-assertions:
    enabled: true
    required-assertions:
      - contains
      - cost
```
