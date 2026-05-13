---
name: run-tests
description: Execute the project test suite with coverage reporting
compatibility: Requires pytest, jest, or go test
metadata:
  author: dx-team
  version: "1.3"
---

# Run Tests

Execute the full test suite for the current project, collect coverage
metrics, and report results in a structured format.

## When to Use This Skill

Use after making code changes to verify nothing is broken, or when the
user explicitly asks to run tests.

## Implementation Steps

### Step 1: Detect Test Framework

Identify the test framework by checking these files in order:
1. `pyproject.toml` or `pytest.ini` → pytest
2. `package.json` with a `test` script → jest / vitest
3. `go.mod` → `go test`
4. `Cargo.toml` → `cargo test`

### Step 2: Run Tests

Execute the test suite with coverage enabled:
- **pytest**: `pytest tests/ -v --cov=src --cov-report=term-missing`
- **jest**: `npx jest --coverage --verbose`
- **go test**: `go test -v -coverprofile=coverage.out ./...`
- **cargo**: `cargo test -- --nocapture`

### Step 3: Parse Results

Extract from the test output:
- Total tests run
- Passed / failed / skipped counts
- Coverage percentage by module
- Names and locations of failing tests

### Step 4: Report Results

Format a markdown summary:
| Metric | Value |
|--------|-------|
| Total  | N     |
| Passed | N     |
| Failed | N     |
| Coverage | N%  |

If any tests failed, include the failure output with file paths and
line numbers.
