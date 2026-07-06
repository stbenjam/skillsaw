---
description: "Repository-wide coding guidelines"
applyTo: "**"
---

- Run `uv run pytest` before pushing; all tests must pass.
- Keep HTTP handlers thin; business logic belongs in `app/services/`.
- Use the structured logger from `app/logging.py`; never `print`.
