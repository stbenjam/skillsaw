"""Shared utilities for builtin rules."""

import json
import re
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml


class FileCache:
    """Thread-safe cache that supports per-file invalidation.

    Each cached function is keyed by its arguments (which must include a
    file path).  ``invalidate(file_path)`` removes only entries whose
    first positional argument matches the given path, so concurrent
    threads operating on different files never interfere with each other.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._stores: List[Dict] = []  # one dict per registered function

    def cached(self, func: Callable) -> Callable:
        """Decorator -- equivalent to ``@lru_cache`` but with per-key eviction."""
        store: Dict[tuple, Any] = {}
        self._stores.append(store)

        def wrapper(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            with self._lock:
                if key in store:
                    return store[key]
            # Compute outside the lock to avoid holding it during I/O.
            result = func(*args, **kwargs)
            with self._lock:
                store[key] = result
            return result

        wrapper._store = store  # type: ignore[attr-defined]
        wrapper.cache_clear = lambda: store.clear()  # type: ignore[attr-defined]
        return wrapper

    def invalidate(self, file_path: Optional[Path] = None):
        """Drop cache entries.

        If *file_path* is given, only entries whose first positional arg
        equals *file_path* are removed -- safe to call from a worker thread
        without disturbing other threads' cached results.

        If *file_path* is ``None`` every entry in every registered store is
        cleared (equivalent to the old ``invalidate_read_caches()``).
        """
        with self._lock:
            if file_path is None:
                for store in self._stores:
                    store.clear()
            else:
                resolved = file_path.resolve()
                for store in self._stores:
                    keys_to_remove = [
                        k
                        for k in store
                        if k[0] and len(k[0]) > 0 and _path_matches(k[0][0], resolved)
                    ]
                    for k in keys_to_remove:
                        del store[k]


def _path_matches(arg: Any, resolved_path: Path) -> bool:
    """Return True if *arg* is a Path that resolves to *resolved_path*."""
    if isinstance(arg, Path):
        try:
            return arg.resolve() == resolved_path
        except (OSError, ValueError):
            return False
    return False


# Singleton cache used by all utility functions.
_file_cache = FileCache()

_extra_caches: list = []


def register_cache(func):
    """Register an lru_cache-decorated function for bulk invalidation."""
    _extra_caches.append(func)
    return func


def invalidate_read_caches(file_path: Optional[Path] = None):
    """Clear file-reading caches.

    Args:
        file_path: When given, only entries for this specific file are
            evicted.  When ``None``, *all* cached entries are dropped
            (legacy full-clear behaviour).
    """
    _file_cache.invalidate(file_path)
    # lru_cache functions registered via register_cache do not support
    # per-key eviction, so we must clear them entirely in both cases.
    for cache in _extra_caches:
        cache.cache_clear()


@_file_cache.cached
def read_text(file_path: Path) -> Optional[str]:
    """Cached file read. Returns None on I/O or encoding errors."""
    try:
        return file_path.read_text(encoding="utf-8")
    except (IOError, UnicodeDecodeError):
        return None


@_file_cache.cached
def read_json(file_path: Path) -> Tuple[Optional[object], Optional[str]]:
    """Cached JSON file read. Returns (data, error)."""
    content = read_text(file_path)
    if content is None:
        return None, f"Failed to read {file_path.name}"
    try:
        return json.loads(content), None
    except json.JSONDecodeError as e:
        return None, str(e)


@_file_cache.cached
def frontmatter_key_line(file_path: Path, key: str) -> Optional[int]:
    """Find the line number of a top-level key in YAML frontmatter."""
    content = read_text(file_path)
    if content is None:
        return None
    pattern = re.compile(rf"^{re.escape(key)}\s*:")
    in_frontmatter = False
    for i, line in enumerate(content.splitlines(), 1):
        if line.strip() == "---":
            if not in_frontmatter:
                in_frontmatter = True
                continue
            break
        if in_frontmatter and pattern.match(line):
            return i
    return None


_FRONTMATTER_RE = re.compile(r"^---[ \t]*\n(.*?\n)---[ \t]*\n?", re.DOTALL)


def parse_frontmatter(content: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """Parse YAML frontmatter from markdown content.

    Returns (frontmatter_dict, body_after_frontmatter).
    If no valid frontmatter is found, returns (None, original_content).
    """
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return None, content
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None, content
    if not isinstance(data, dict):
        return None, content
    body = content[m.end() :]
    return data, body


def extract_section(content: str, heading: str, level: int = 2) -> str:
    """Extract content under a markdown heading, up to the next heading of same or higher level."""
    prefix = "#" * level
    pattern = re.compile(
        rf"^{prefix}[ \t]+{re.escape(heading)}[ \t]*$\r?\n?(.*?)(?=^#{{{1},{level}}}[ \t]|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(content)
    return m.group(1).strip() if m else ""


@_file_cache.cached
def heading_line(file_path: Path, heading: str, level: int = 2) -> Optional[int]:
    """Find the line number of a markdown heading."""
    content = read_text(file_path)
    if content is None:
        return None
    prefix = "#" * level
    pattern = re.compile(rf"^{prefix}\s+{re.escape(heading)}\s*$")
    for i, line in enumerate(content.splitlines(), 1):
        if pattern.match(line):
            return i
    return None
