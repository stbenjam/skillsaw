---
description: Run the project linter and report findings
---

## Name
lint

## Synopsis
```text
/lint [--fix]
```

## Description
Runs the configured linter (`flake8` and `mypy`) against the current
project and reports any style or correctness violations found.

If `--fix` is passed, runs `black` and `isort` to auto-fix formatting
issues before reporting remaining violations.

## Implementation
1. If `--fix` is passed, run `black src/ tests/` and `isort src/ tests/`
2. Run `flake8 src/ tests/` and capture the output
3. Run `mypy src/` and capture type-checking results
4. Parse both outputs into a unified list of violations
5. Group violations by file path and present them with line numbers
6. Report total error and warning counts
