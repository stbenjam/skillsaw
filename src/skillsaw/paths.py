"""Path helpers shared across formats and rule packages.

The pure predicates answer questions about a path *string* — is it
absolute, does it escape its root — without touching the filesystem.
The ``safe_*`` wrappers are their filesystem-touching companions:
``pathlib`` calls that never raise, so discovery and rules can probe
manifest-supplied paths without aborting the lint.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Optional


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


def safe_resolve(path: Path) -> Optional[Path]:
    """``path.resolve()``, or ``None`` when the path cannot be resolved.

    Discovery runs while ``RepositoryContext`` is being constructed, before
    any rule can report anything, and it resolves strings taken straight
    out of a manifest. ``Path.resolve()`` raises ``ValueError`` on an
    embedded NUL, ``OSError`` on an unreadable parent, and — on a symlink
    loop — ``RuntimeError`` before Python 3.13 but ``OSError`` from 3.13
    on. This project supports 3.9 through 3.14, so all three have to be
    caught; any of them would abort the whole lint instead of producing
    the violation the manifest deserves. Returning ``None`` drops the
    candidate from discovery and leaves the reporting to the rules.
    """
    try:
        return path.resolve()
    except (OSError, ValueError, RuntimeError):
        return None


def contained_resolve(path: Path, root: Path) -> Optional[Path]:
    """``path`` resolved, when it stays inside *root* — else ``None``.

    The reject-a-symlink-escape idiom in one place: a resolution failure
    and a path that resolves outside *root* both yield ``None``, so a
    caller holding a resolved root can write ``if contained_resolve(p,
    root) is None: reject``.
    """
    resolved = safe_resolve(path)
    if resolved is None or not resolved.is_relative_to(root):
        return None
    return resolved


def _safe_stat(path: Path, predicate: str) -> bool:
    """``path.<predicate>()``, or ``False`` when the path cannot be stat'd.

    ``safe_resolve`` is not enough on its own: ``Path.resolve()`` does not
    stat, so it happily returns a path that the very next ``is_dir()``
    raises on. ``pathlib`` swallows only ``ENOENT``/``ENOTDIR``/``EBADF``/
    ``ELOOP`` on Python 3.9 through 3.12, so a manifest declaring a
    4000-character path raises ``ENAMETOOLONG`` there — from inside
    ``RepositoryContext.__init__``, where the ``rule-execution-error``
    guard cannot reach it. The whole lint aborts with a traceback and
    reports nothing at all, on a repository whose only defect is one
    over-long string in a JSON file.
    """
    try:
        return bool(getattr(path, predicate)())
    except (OSError, ValueError):
        return False


def safe_is_dir(path: Path) -> bool:
    """``path.is_dir()``, or ``False`` when the path cannot be stat'd."""
    return _safe_stat(path, "is_dir")


def safe_is_file(path: Path) -> bool:
    """``path.is_file()``, or ``False`` when the path cannot be stat'd."""
    return _safe_stat(path, "is_file")


def safe_exists(path: Path) -> bool:
    """``path.exists()``, or ``False`` when the path cannot be stat'd."""
    return _safe_stat(path, "exists")


def safe_is_symlink(path: Path) -> bool:
    """``path.is_symlink()``, or ``False`` when the path cannot be stat'd."""
    return _safe_stat(path, "is_symlink")


def escapes_root(value: str, root: Path) -> bool:
    """Whether *value* resolves outside *root* once symlinks are followed.

    A path that does not exist yet cannot escape through a link, so an
    unresolvable candidate is left to the caller's existence check. ``OSError``
    (a symlink loop, an unreadable parent) counts as an escape: the linter
    cannot prove containment, and failing closed is the safe direction for a
    check whose whole purpose is keeping discovery inside the root.
    """
    try:
        resolved_root = root.resolve()
        candidate = (root / value).resolve()
    except (OSError, ValueError, RuntimeError):
        # Unreadable parent, symlink loop (OSError on 3.13+, RuntimeError
        # before), or embedded NUL: containment cannot be proven, so fail
        # closed.
        return True
    return candidate != resolved_root and not candidate.is_relative_to(resolved_root)
