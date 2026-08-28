# AGENTS.md

Conventions for the `billing-api` service. OpenCode reads this file on every
turn, so keep it short and specific.

## Build and test

- Install dependencies with `uv sync`.
- Run the unit suite with `uv run pytest tests/unit`.
- Run the integration suite with `uv run pytest tests/integration`. It needs
  a local Postgres; start one with `docker compose up -d db`.

## Code conventions

- Format with `uv run ruff format`. CI rejects unformatted code.
- Every public function takes typed arguments and returns a typed value.
- Database access goes through `billing.repository`. Do not import
  `sqlalchemy` outside that module.

## Pull requests

- One logical change per pull request.
- Reference the issue number in the title, e.g. `BILL-1204: retry dunning`.
- Update `CHANGELOG.md` when the change is user-visible.
