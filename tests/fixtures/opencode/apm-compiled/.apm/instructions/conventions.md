# Shipping platform conventions

These are the APM sources. Edit them here; `apm compile` writes the copies
each tool reads.

## Build and test

- Install dependencies with `uv sync`.
- Run the unit suite with `uv run pytest tests/unit`.
- Run the carrier integration suite with `uv run pytest tests/carriers`. It
  needs the sandbox credentials in `.env.sandbox`.

## Code conventions

- Format with `uv run ruff format`. CI rejects unformatted code.
- Carrier API calls go through `shipping.carriers.client`. Do not call
  `httpx` directly from a handler.
- Weights are integers of grams. Never use a floating-point type.

## Pull requests

- One logical change per pull request.
- Reference the issue key in the title, e.g. `SHIP-402: retry label buys`.
