# Agent Instructions

This service powers the order-processing pipeline for the storefront. It is
a Python 3.12 application managed with uv; the API layer is FastAPI and the
worker processes consume from RabbitMQ.

- Install dependencies with `uv sync` before running anything.
- Run the test suite with `uv run pytest`. Tests must pass before you push.
- Format with `uv run ruff format` and lint with `uv run ruff check --fix`.
- Business logic lives in `app/services/`; keep HTTP handlers thin.
