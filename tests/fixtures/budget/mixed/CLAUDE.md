# Project Instructions

This service powers the order-processing pipeline for the storefront. It is
a Python 3.12 application managed with uv; the API layer is FastAPI and the
worker processes consume from RabbitMQ.

@docs/architecture.md

## Development workflow

- Install dependencies with `uv sync` before running anything.
- Run the test suite with `uv run pytest`. Tests must pass before you push.
- Format with `uv run ruff format` and lint with `uv run ruff check --fix`.
- Database migrations live in `migrations/` and are applied with
  `uv run alembic upgrade head`. Never edit an applied migration; add a new
  revision instead.

## Architecture notes

- `app/api/` holds the HTTP layer. Handlers must stay thin: validate input,
  call a service function, serialize the result.
- `app/services/` is where business logic lives. Service functions take and
  return plain dataclasses, never ORM models.
- `app/workers/` contains queue consumers. Each consumer is idempotent —
  messages are redelivered at least once.
- Configuration comes from environment variables parsed in `app/config.py`.
  Do not read `os.environ` anywhere else.

## Conventions

- Prefer explicit imports over wildcard imports.
- New endpoints need an OpenAPI description and a request/response example.
- Log with the structured logger from `app/logging.py`; never use `print`.
