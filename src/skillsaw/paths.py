"""Pure path predicates shared across formats and rule packages.

These answer questions about a path *string* — is it absolute, does it
escape its root — without touching the filesystem. They live here rather
than in a rule module because two independent rule packages need them,
and a rule package importing from another rule package is the only such
edge in the tree. ``skillsaw.formats.codex.safe_resolve`` is the
filesystem-touching companion.
"""

from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath


def is_absolute_path(path: str) -> bool:
    """True for POSIX-absolute (/x) or Windows-absolute (C:\\x, \\\\share) paths."""
    return PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute()


def has_parent_traversal(path: str) -> bool:
    """True when the path contains a '..' component."""
    return ".." in path.replace("\\", "/").split("/")
