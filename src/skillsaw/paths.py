"""Path helpers shared across formats and rule packages.

The pure predicates answer questions about a path *string* — is it
absolute, does it escape its root — without touching the filesystem.
The ``safe_*`` wrappers are their filesystem-touching companions:
``pathlib`` calls that never raise, so discovery and rules can probe
manifest-supplied paths without aborting the lint.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import AbstractSet, Dict, Optional

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
# Absolute paths only. A relative path names a different file after a
# ``chdir``, and the key does not say which directory the answer was
# resolved under — so a library embedding skillsaw, which reaches
# ``safe_resolve`` through the public ``init_marketplace(path=...)`` and
# component-add helpers without ever building a context, would get the
# first working directory's repository back for the second one's path.
# Skipping the memo there rather than widening the key keeps the lookup a
# single dict ``get``: reading ``Path.cwd()`` per call to build a keyable
# absolute form costs a syscall on the hot path to serve one caller per
# run. A self-lint resolves 4,636 absolute paths and one relative one —
# the root the CLI was handed, which it resolves before joining anything
# onto it, so every path derived from it is absolute and still memoized.
# Since no relative path is stored, none can be answered from here, and
# the check that keeps them out sits in the miss branch.
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

#: How many copies of its own string a ``Path`` keeps alive. CPython holds
#: the rendered path in ``_str`` and the components separately — through
#: ``_parts`` before 3.12, and ``_raw_paths`` plus a normcase cache from
#: 3.12 on. Measured with a one-million-character component, the distinct
#: strings retained come to 2x the rendered size on 3.11 and 3x on 3.12 and
#: 3.13, so a path's content is charged three times rather than once. The
#: per-component term below covers a path's *structure*; this covers its
#: *length*, and a path can be oversized in either direction.
_PATH_STRING_COPIES = 3

#: Charged per path component. ``sys.getsizeof`` on a ``Path`` is shallow:
#: the object keeps its components in ``__slots__`` — the parts tuple, and
#: a second cased copy once anything compares paths — so the string is not
#: the whole of what an entry holds. Measured against real RSS over 40,000
#: ordinary repository paths, 2,000 of 200 distinct components each, and
#: 300 of one 50,000-character component — each in a *fresh* process,
#: because ``ru_maxrss`` reports a peak and a second measurement in the
#: same process reads against whatever the first one already reached. The
#: many-component shape is the demanding one at ~43 bytes per component;
#: 64 leaves room for the layout differing across supported Pythons.
_RESOLVE_COMPONENT_BYTES = 64

#: Serializes admission only. Lookups stay lock-free, so the hit path — the
#: whole point of the memo — is untouched; two threads missing the same
#: path would otherwise both insert one dict entry and both charge for it,
#: and a counter that over-reports has the memo stop accepting early and
#: quietly give back the speed it exists for.
_resolve_lock = threading.Lock()

#: Bumped by every clear, and captured before ``Path.resolve()`` runs. The
#: resolution happens outside the lock, so a clear can land between the
#: syscall and the insert — and without this the answer from before the
#: change is written in *after* the drop meant to remove it, and every
#: later containment check and cached read is handed a target the
#: filesystem no longer has. ``FileCache`` carries the same counter for
#: the same reason; this memo is a separate global and is not covered by
#: it.
_resolve_generation = 0

#: What the memo may retain. A count cap cannot express this bound, because
#: a ``Path`` is not fixed-small: manifests supply path strings, and at the
#: 4 KB a filesystem permits, a quarter-million of them measured 2.1 GB
#: resident. The budget has to sit well above what a real repository needs —
#: every rule sweeps the same set, so a bound the repository can cross is a
#: cliff rather than a limit, and past it the memo silently gives back the
#: 2.6s it exists for.
#:
#: A large skill marketplace holds ~18.3k distinct paths for ~59.7 MB
#: charged, so 64 MiB would sit at 93% of the bound with a slightly
#: larger repository falling off it. The bound states what such a
#: repository holds, with room above it.
#:
#: Note the charge is deliberately conservative — measured at 1.2x to 1.9x
#: real RSS across path shapes — so this bound is not the memory it
#: permits. 256 MiB nominal corresponds to roughly 135-210 MB resident.
_RESOLVE_CACHE_BUDGET_BYTES = 256 * 1024 * 1024

#: Charged so far. Once the budget is reached the memo simply stops
#: accepting entries: it is a pure speed optimization over a filesystem
#: that has not changed, so declining to remember costs time and nothing
#: else. Evicting instead would be the cliff described above.
_resolve_cache_bytes = 0


def _path_cost(path: Path) -> int:
    """Bytes *path* retains: its string, the ``Path``, and its components.

    ``len()`` is a character count, not a byte count. CPython stores one,
    two or four bytes per character (PEP 393), so a path of emoji retains
    four times what ``len`` reports and one of CJK twice — and a manifest
    chooses those characters, not this repository. The same correction the
    file cache makes for cached text, for the same reason.

    Nor is one copy of that string the whole of it: a ``Path`` keeps its
    components alive separately from the rendered path, so the same text is
    retained two or three times over depending on the interpreter.

    ``getsizeof`` on the ``Path`` is not the rest of it, either: it reports
    the object's own struct and not the components hanging off its slots.
    They are counted rather than walked — a separator count is a C-speed
    scan of a string already built, where a walk down every entry would
    cost more than the resolution it is accounting for.
    """
    text = str(path)
    components = text.count(os.sep) + 1
    if os.altsep:
        components += text.count(os.altsep)
    return (
        sys.getsizeof(text) * _PATH_STRING_COPIES
        + sys.getsizeof(path)
        + components * _RESOLVE_COMPONENT_BYTES
    )


def clear_resolve_cache() -> None:
    """Drop every memoized resolution.

    Called by ``invalidate_read_caches()`` so path resolution and file
    reads share one invalidation point: after autofix rewrites the tree,
    neither may answer from the pre-fix filesystem.
    """
    global _resolve_cache_bytes, _resolve_generation
    with _resolve_lock:
        _resolve_generation += 1
        _RESOLVE_CACHE.clear()
        _resolve_cache_bytes = 0


def path_within_roots(path: Path, roots: AbstractSet[Path]) -> bool:
    """Whether resolved *path* equals or descends from an indexed root."""
    return path in roots or any(parent in roots for parent in path.parents)


def resolve_generation() -> int:
    """The memo's current generation, for a cache keyed on its answers.

    ``FileCache`` keys entries on resolved paths, so a read that spans a
    clear resolved under one filesystem and is admitted under another.
    Its own generation cannot see that: the two are bumped by separate
    statements, and a reader finishing between them passes a check
    against the one that has not moved yet.
    """
    return _resolve_generation


def safe_resolve(path: Path) -> Optional[Path]:
    """``path.resolve()``, or ``None`` when the path cannot be resolved.

    Memoized for the lifetime of one lint pass, absolute paths only; see
    ``_RESOLVE_CACHE``.

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
    generation = _resolve_generation
    try:
        resolved: Optional[Path] = path.resolve()
    except (OSError, ValueError, RuntimeError):
        resolved = None
    if not path.is_absolute():
        # Tested here rather than ahead of the lookup: no relative path is
        # ever stored, so its lookup always misses anyway, and the check
        # stays off the path every cache hit takes.
        return resolved
    global _resolve_cache_bytes
    cost = _RESOLVE_ENTRY_OVERHEAD_BYTES + _path_cost(path)
    if resolved is not None:
        cost += _path_cost(resolved)
    with _resolve_lock:
        # Rechecked under the lock: another caller may have resolved the
        # same path while this one was in ``Path.resolve()``, and the
        # entry it inserted is already charged. Charging again would bill
        # one dict entry twice. A clear landing in that same window means
        # this answer predates it — hand it to the caller that asked, but
        # do not file it where it would outlive the drop.
        if (
            _resolve_generation == generation
            and path not in _RESOLVE_CACHE
            and _resolve_cache_bytes + cost <= _RESOLVE_CACHE_BUDGET_BYTES
        ):
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
