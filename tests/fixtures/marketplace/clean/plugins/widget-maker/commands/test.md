---
description: Run widget test suite against compiled artifacts
argument-hint: "[widget-name] [--coverage]"
---

## Name
widget-maker:test

## Synopsis
```
/widget-maker:test my-widget --coverage
```

## Description
Runs the widget test suite against the compiled output in `dist/`.
Optionally generates a coverage report.

## Implementation
1. Locate the test files in `tests/widgets/`
2. Run the test runner with `npm test -- --widget $WIDGET_NAME`
3. If `--coverage` is set, append `--coverage` to the test command
4. Parse the test output for pass/fail counts
5. Display results as a summary table with test names and outcomes
