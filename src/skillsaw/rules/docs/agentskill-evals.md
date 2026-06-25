## Why

When an `evals/evals.json` file exists, it must conform to the
expected schema so that eval runners can execute it. Malformed JSON,
missing required fields, or invalid test structures will cause eval
runs to fail silently or produce misleading results.

## Examples

**Bad:**

```json
[{"input": "deploy to staging"}]
```

**Good:**

```json
{
  "evals": [
    {
      "input": "deploy to staging",
      "expected": "Deployment initiated to staging environment"
    }
  ]
}
```

## How to fix

Fix the JSON structure to match the expected eval schema. Each test
case needs at minimum an `input` and `expected` field. The violation
message identifies the specific structural problem — address it
directly.
