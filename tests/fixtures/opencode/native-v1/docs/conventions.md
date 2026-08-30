# Service conventions

Keep HTTP handlers thin. Parse and validate requests at the boundary, then
delegate business logic to `billing.service`.

Run `uv run pytest tests/unit` before committing a change.
