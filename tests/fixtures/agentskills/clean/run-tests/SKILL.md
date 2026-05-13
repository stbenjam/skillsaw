---
name: run-tests
description: Execute the project test suite with coverage reporting
---

# Run Tests

Execute the full test suite for the current project, collect coverage
metrics, and report results in a structured format.

## When to Use This Skill

Use after making code changes to verify nothing is broken, or when the
user explicitly asks to run tests.

## Implementation Steps

### Step 1: Detect Test Framework

Identify which test framework the project uses by checking for pytest,
jest, go test, or other common configurations.

### Step 2: Run Tests

Execute the test suite with coverage collection enabled.

### Step 3: Report Results

Summarize pass/fail counts, coverage percentage, and any failing test
details with file and line references.
