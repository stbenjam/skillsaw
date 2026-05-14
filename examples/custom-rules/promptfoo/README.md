# Custom Rule Example: promptfoo-budget

This example demonstrates how to write a custom skillsaw rule that validates
promptfoo eval tests against a centralized budget/policy file.

## Files

| File | Description |
|------|-------------|
| `promptfoo_budget_rule.py` | The custom rule implementation |
| `budget.yaml` | Example budget policy file |
| `fixture/` | A test repo that exercises the rule |

## What it enforces

Given a `budget.yaml` that defines cost tiers, judge-size orderings, and
per-plugin budgets, the rule validates every promptfoo eval test:

1. **Required metadata** — `token-usage`, `judge-size`, and `tier` must be present
2. **token-usage accuracy** — cost/latency thresholds must fit the declared size,
   and the size must be the lowest one that fits (flags over-classification)
3. **judge-size consistency** — must be `none` when there are no `llm-rubric`
   assertions, and non-`none` when there are
4. **tier accuracy** — must be the lowest tier where both token-usage and
   judge-size fit
5. **budget compliance** — total cost thresholds per plugin must not exceed the
   allowed budget

## Usage

1. Copy `promptfoo_budget_rule.py` and `budget.yaml` into your repo
2. Add to `.skillsaw.yaml`:

```yaml
custom-rules:
  - evals/budget_rule.py   # path to the rule file

rules:
  promptfoo-budget:
    enabled: true
    severity: error
    budget-file: evals/budget.yaml   # default
```

3. Run:

```bash
skillsaw lint --rule promptfoo-budget
```

## Try the fixture

```bash
cd fixture
skillsaw lint --rule promptfoo-budget .
```

Expected output — 2 errors and 1 warning:

- `greeting-quality` has `judge-size: none` but uses `llm-rubric` assertions
- `hello-world` total cost ($1.50) exceeds budget ($1.00)
- `greeting-named` is classified as `medium` but fits in `small`
