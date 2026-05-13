---
description: Run the project test suite with optional coverage
---

## Name
test

## Synopsis
```
/test [--coverage] [path]
```

## Description
Runs pytest against the project test suite. Optionally generates a
coverage report and limits the run to a specific test path.

## Implementation
1. Build the pytest command: `pytest tests/ -v`
2. If `--coverage` is passed, append `--cov=src --cov-report=term-missing`
3. If a path argument is given, replace `tests/` with the specified path
4. Execute the command and stream output to the user
5. Parse the exit code: 0 = all passed, 1 = failures, 2 = errors
6. Summarize: total tests, passed, failed, skipped, and coverage percentage
