---
name: review
description: Review the current branch for merge readiness
---

# Review

Check the current branch for merge readiness by running tests, verifying
lint passes, and confirming documentation is updated.

## When to Use

Use before creating a pull request or when asked to verify the branch
is ready to merge.

## Implementation Steps

### Step 1: Run Tests

Execute the full test suite:
```bash
pytest tests/ -v --tb=short
```
All tests must pass. If any fail, report the failures and stop.

### Step 2: Check Lint

Run the linter and confirm no new violations:
```bash
flake8 src/ tests/
mypy src/
```

### Step 3: Check Formatting

Verify code is formatted:
```bash
black --check src/ tests/
isort --check-only src/ tests/
```

### Step 4: Verify Docs

If any public API signatures changed, check that the corresponding
docstrings and `docs/` files are updated.

### Step 5: Summary

Report a markdown checklist:
- [ ] Tests pass
- [ ] Lint clean
- [ ] Formatting clean
- [ ] Docs updated (if applicable)
