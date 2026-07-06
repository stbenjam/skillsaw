# Gemini Instructions

This is the order-processing service for the storefront. Python 3.12,
FastAPI API layer, RabbitMQ workers, managed with uv.

- Run `uv sync` to install dependencies and `uv run pytest` to test.
- Keep HTTP handlers thin; business logic belongs in `app/services/`.
- Configuration is read only in `app/config.py`.
