---
name: debug
description: Investigate and diagnose test failures or runtime errors
---

# Debug

Investigate test failures, runtime errors, or unexpected behavior by
tracing the code path and identifying the root cause.

## When to Use

Use when a test fails and the cause is not obvious from the error
message, or when the user reports unexpected runtime behavior.

## Implementation Steps

### Step 1: Reproduce

Run the failing test in isolation with verbose output:
```bash
pytest tests/path/to/test.py::TestClass::test_method -vvs
```

### Step 2: Read the Traceback

Identify the exception type, message, and the deepest frame in project
code (ignore frames in third-party libraries).

### Step 3: Trace the Code Path

Read the source file at the line indicated by the traceback. Follow the
call chain upward to understand how the function was invoked and what
inputs it received.

### Step 4: Identify Root Cause

Determine whether the failure is caused by:
- Incorrect input data or test setup
- A logic error in the code under test
- A missing or incorrect mock/stub
- An environmental issue (missing dependency, wrong Python version)

### Step 5: Suggest Fix

Propose a minimal fix with the exact file path and line number.
