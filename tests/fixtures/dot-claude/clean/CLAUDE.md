# Project Guidelines

This project uses Python 3.11 and pytest for testing. Run `make test`
to execute the full test suite.

## Code Standards

- Format code with `black --line-length 100` before committing
- Type annotations are required on all public functions
- Every module must have a one-line docstring
- Run `make lint` to check for style violations

## Pre-commit Checklist

1. Run `make test` — all tests must pass
2. Run `make lint` — no new lint violations
3. Run `make format` — code is formatted
4. Update `CHANGELOG.md` if the change is user-facing

## Architecture

The project follows a layered architecture:
- `src/core/` — domain models and business logic
- `src/api/` — HTTP request handlers
- `src/db/` — database access and migrations
- `tests/` — test files mirroring the `src/` structure

## Dependencies

- Add runtime dependencies to `pyproject.toml` under `[project.dependencies]`
- Add dev dependencies under `[project.optional-dependencies.dev]`
- Pin major versions only: `requests>=2.28,<3`
