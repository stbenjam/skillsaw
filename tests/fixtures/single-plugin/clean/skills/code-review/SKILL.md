---
name: code-review
description: Review code changes for correctness, style compliance, and test coverage
---

# Code Review

Analyze pull request diffs and changed files to identify potential issues
including logic errors, missing edge case handling, and style violations.

## When to Use

Invoke this skill when the user asks to review code, check a pull request,
or analyze recent changes for quality issues.

## Implementation Steps

### Step 1: Gather Changes

Read the diff or list of changed files from the current branch.

### Step 2: Analyze Each File

For each changed file:
- Check for logic errors and off-by-one bugs
- Verify error handling covers failure modes
- Confirm naming conventions match project standards

### Step 3: Check Test Coverage

Verify that new or modified functions have corresponding test cases.

### Step 4: Report Findings

Present findings grouped by severity with file and line references.
