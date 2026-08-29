"""Path helpers shared across formats and rule packages.

The pure predicates answer questions about a path *string* — is it
absolute, does it escape its root — without touching the filesystem.
The ``safe_*`` wrappers are their filesystem-touching companions:
``pathlib`` calls that never raise, so discovery and rules can probe
manifest-supplied paths without aborting the lint.
"""

from __future__ import annotations

import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Dict, Optional

# Sentinel distinguishing "not memoized" from a memoized ``None``.
_MISSING = object()


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


# Resolution memo, shared by every ``safe_resolve`` caller.
#
# ``Path.resolve()`` lstats every component of every path it is handed, and
# skillsaw resolves the same handful of directory chains thousands of times
# per run: once per cached file read (``FileCache`` keys on the resolved
# path), once per containment check, once per rule that maps a node back to
# its file. The repository is a fixed snapshot for the duration of a lint,
# so the answers are stable — and the one thing that can change them,
# autofix writing to disk between passes, already funnels through
# ``invalidate_read_caches()``, which clears this memo alongside the file
# caches (see ``skillsaw.utils``).
_RESOLVE_CACHE: Dict[Path, Optional[Path]] = {}

#: Charged on top of what the two paths themselves measure, for the dict
#: entry holding them: hash, key and value pointers, and the slack a hash
#: table carries between resizes.
_RESOLVE_ENTRY_OVERHEAD_BYTES = 256

#: What the memo may retain. A count cap cannot express this bound, because
#: a ``Path`` is not fixed-small: manifests supply path strings, and at the
#: 4 KB a filesystem permits, a quarter-million of them measured 2.1 GB
#: resident. The budget has to sit well above what a real repository needs —
#: a large skill marketplace resolves ~20.5k distinct paths for ~17.3 MB
#: charged here — because every rule sweeps the same set, so a bound the
#: repository can cross is a cliff rather than a limit.
_RESOLVE_CACHE_BUDGET_BYTES = 64 * 1024 * 1024

#: Charged so far. Once the budget is reached the memo simply stops
#: accepting entries: it is a pure speed optimization over a filesystem
#: that has not changed, so declining to remember costs time and nothing
#: else. Evicting instead would be the cliff described above.
_resolve_cache_bytes = 0


def _path_cost(path: Path) -> int:
    """Bytes *path* retains: its string, plus the ``Path`` holding it.

    ``len()`` is a character count, not a byte count. CPython stores one,
    two or four bytes per character (PEP 393), so a path of emoji retains
    four times what ``len`` reports and one of CJK twice — and a manifest
    chooses those characters, not this repository. The same correction the
    file cache makes for cached text, for the same reason.
    """
    return sys.getsizeof(str(path)) + sys.getsizeof(path)


def clear_resolve_cache() -> None:
    """Drop every memoized resolution.

    Called by ``invalidate_read_caches()`` so path resolution and file
    reads share one invalidation point: after autofix rewrites the tree,
    neither may answer from the pre-fix filesystem.
    """
    global _resolve_cache_bytes
    _RESOLVE_CACHE.clear()
    _resolve_cache_bytes = 0


def safe_resolve(path: Path) -> Optional[Path]:
    """``path.resolve()``, or ``None`` when the path cannot be resolved.

    Memoized for the lifetime of one lint pass; see ``_RESOLVE_CACHE``.

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
    cached = _RESOLVE_CACHE.get(path, _MISSING)
    if cached is not _MISSING:
        return cached  # type: ignore[return-value]
    try:
        resolved: Optional[Path] = path.resolve()
    except (OSError, ValueError, RuntimeError):
        resolved = None
    global _resolve_cache_bytes
    cost = _RESOLVE_ENTRY_OVERHEAD_BYTES + _path_cost(path)
    if resolved is not None:
        cost += _path_cost(resolved)
    if _resolve_cache_bytes + cost <= _RESOLVE_CACHE_BUDGET_BYTES:
        _RESOLVE_CACHE[path] = resolved
        _resolve_cache_bytes += cost
    return resolved


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
