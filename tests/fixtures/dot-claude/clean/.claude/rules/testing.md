Every new function or method must have a corresponding test. Place test
files in `tests/` mirroring the `src/` directory structure.

Use `pytest` fixtures for shared setup. Prefer `tmp_path` over manual
temp directory management.

Mark slow tests with `@pytest.mark.slow` so they can be skipped during
rapid iteration with `pytest -m "not slow"`.
