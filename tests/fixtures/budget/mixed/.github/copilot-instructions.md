# Copilot Instructions

Order-processing service: Python 3.12, FastAPI, RabbitMQ workers, uv for
dependency management.

- `uv run pytest` must pass before pushing.
- Keep HTTP handlers thin; put business logic in `app/services/`.
- Use the structured logger from `app/logging.py`; never `print`.
