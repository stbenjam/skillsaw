# Code Style

- Use type hints on every public function signature.
- Keep functions under 50 lines; extract helpers when they grow past that.
- Docstrings follow the Google style guide and describe behavior, not
  implementation details.
- Raise domain-specific exceptions from `app/errors.py` instead of bare
  `ValueError` or `RuntimeError`.
