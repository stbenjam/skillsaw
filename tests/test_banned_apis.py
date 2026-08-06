"""Ban unsafe path resolution calls in skillsaw source.

``Path.resolve()`` raises ``OSError``, ``ValueError``, or ``RuntimeError``
on hostile input (symlink loops, embedded NULs, unreadable parents), which
is why ``skillsaw.paths`` provides ``safe_resolve()`` and
``contained_resolve()``. New call sites must make their failure policy explicit
through one of those wrappers instead of reaching for the unsafe APIs directly.
"""

import ast
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "skillsaw"


def _unsafe_path_calls() -> list[str]:
    """Locations of bare ``.resolve()`` or ``os.path.realpath`` calls.

    The scan is AST-based so docstrings and comments mentioning
    ``path.resolve()`` do not count — only an actual attribute call named
    ``resolve`` does. ``safe_resolve()``/``contained_resolve()`` are plain
    function calls, not attribute calls, so they never match.
    """
    offenders = []
    for py in sorted(SRC_ROOT.rglob("*.py")):
        rel = py.relative_to(SRC_ROOT).as_posix()
        if rel == "paths.py":
            continue
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "resolve"
            ):
                offenders.append(f"{rel}:{node.lineno}: .resolve()")
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "realpath"
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "path"
                and isinstance(node.func.value.value, ast.Name)
                and node.func.value.value.id == "os"
            ):
                offenders.append(f"{rel}:{node.lineno}: os.path.realpath()")
    return offenders


class TestBannedApis:
    def test_no_unsafe_path_resolution_calls(self):
        """Skillsaw source must use the safe path-resolution wrappers."""
        offenders = _unsafe_path_calls()
        assert not offenders, (
            "Unsafe path-resolution calls found: "
            f"{offenders}. Use safe_resolve() or "
            "contained_resolve() from skillsaw.paths instead — Path.resolve() "
            "raises on symlink loops, embedded NULs, and unreadable parents."
        )
