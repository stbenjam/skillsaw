---
description: Bump the skillsaw version correctly
---

# Bump Version

To bump the skillsaw version:

1. Run `scripts/bump-version.sh` (auto-increments patch) or `scripts/bump-version.sh X.Y.Z` for a specific version
2. This updates both `pyproject.toml` and `src/skillsaw/__init__.py`
3. Verify: `python -c "from skillsaw import __version__; print(__version__)"`
4. Run tests: `pytest tests/ -v`
5. Commit with message: `Bump version to X.Y.Z`
