## Why

Metadata keys on eval tests (like `category`, `priority`, or
`owner`) enable filtering and reporting across a large test suite.
This opt-in rule enforces that every test case includes the metadata
keys you configure.

## Examples

**Bad:**

```yaml
tests:
  - vars:
      input: "deploy"
    assert:
      - type: contains
        value: "deployed"
```

**Good:**

```yaml
tests:
  - vars:
      input: "deploy"
    metadata:
      category: deployment
      priority: high
    assert:
      - type: contains
        value: "deployed"
```

## How to fix

Add the required `metadata` keys to each test case. Configure which
keys are required:

```yaml
rules:
  promptfoo-metadata:
    enabled: true
    required-metadata:
      - category
```
