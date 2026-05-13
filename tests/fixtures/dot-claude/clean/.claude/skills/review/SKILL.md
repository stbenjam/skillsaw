---
name: review
description: Review the current branch for merge readiness
---

# Review

Check the current branch for merge readiness by verifying tests pass,
lint is clean, and documentation is updated.

## When to Use

Use before creating a pull request or when asked to verify the branch
is ready to merge.

## Implementation Steps

### Step 1: Run Tests

Execute the test suite and verify all tests pass.

### Step 2: Check Lint

Run the linter and confirm no new violations.

### Step 3: Verify Docs

Check that any public API changes have corresponding documentation updates.
