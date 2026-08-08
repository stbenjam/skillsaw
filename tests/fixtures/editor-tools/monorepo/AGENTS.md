# Contributing agent instructions

This is a small monorepo: `apps/web` is the front end, `services/api` is the
Python backend.

## Build and test

- Install dependencies with `make setup`.
- Run `make test` before opening a pull request.
- Run `make lint` and fix every reported issue.

## Conventions

- Python code targets 3.11 and uses type hints on public functions.
- TypeScript code runs under `strict` mode.
