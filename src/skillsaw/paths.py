"""Pure path predicates shared across formats and rule packages.

These answer questions about a path *string* — is it absolute, does it
escape its root — without touching the filesystem. They live here rather
than in a rule module because two independent rule packages need them,
and neither should have to import the other's private helpers to get at
a pure predicate. ``skillsaw.formats.codex.safe_resolve`` is the
filesystem-touching companion.
"""

from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath


def is_absolute_path(path: str) -> bool:
    """True for POSIX-absolute (/x) or Windows-absolute (C:\\x, \\\\share) paths.

    ``PureWindowsPath.is_absolute()`` is False for a drive-relative path
    like ``\\Windows\\System32``: it has a root but no drive, so Windows
    resolves it against the *current* drive. That is still rooted, and
    still outside the plugin. Testing the root as well as ``is_absolute()``
    catches it on any host — linting on Linux, the backslashes would
    otherwise read as ordinary filename characters and the containment
    check would pass a path Codex resolves out of the checkout on Windows.
    """
    if PurePosixPath(path).is_absolute():
        return True
    windows = PureWindowsPath(path)
    # Three separate shapes, and ``is_absolute()`` only covers the first:
    #   C:\\x          drive + root  -> absolute
    #   \\Windows\\x   root, no drive -> current drive's root
    #   C:plugins\\x   drive, no root -> drive C's *current directory*
    # The last two resolve somewhere this repository does not control, so
    # a containment check that accepts them is not a containment check.
    return windows.is_absolute() or bool(windows.root) or bool(windows.drive)


def has_parent_traversal(path: str) -> bool:
    """True when the path contains a '..' component."""
    return ".." in path.replace("\\", "/").split("/")
