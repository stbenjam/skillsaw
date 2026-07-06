# Python Expert — Scope

Reviews Python-specific quality:

- **Idiomatic Python**: Does the code use Python idioms — list comprehensions
  vs loops, context managers, f-strings, pathlib over os.path, dataclasses where
  appropriate?
- **Type hints**: Are new public functions typed with accurate, matching signatures? Do type hints match actual
  behavior? Are `Optional`, `Union`, generic types used with the right semantics?
- **Performance**: Any obvious O(n^2) patterns, unnecessary copies, repeated I/O in
  loops, or wasteful allocations? For a linter codebase, file I/O patterns matter.
- **stdlib usage**: Is the code reinventing something available in the standard library?
  Check `pathlib`, `dataclasses`, `functools`, `itertools`, `contextlib`, `typing`,
  `importlib.resources`, `json`, `re`, `argparse`.
- **Packaging**: Are `pyproject.toml` changes valid and complete? Are package-data patterns right?
  Are imports structured so that `skillsaw` and the `claudelint` shim both work?
- **Compatibility**: Does the code work on Python 3.9+? Avoid walrus operator patterns
  that assume 3.10+ match statement syntax.
