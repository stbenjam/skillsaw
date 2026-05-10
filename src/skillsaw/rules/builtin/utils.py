"""Shared utilities for builtin rules."""

import json
import re
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml


class FileCache:
    """Thread-safe cache that supports per-file invalidation.

    Internally uses a two-level dictionary::

        resolved_path -> { sub_key -> value }

    ``invalidate(file_path)`` is O(1) -- it pops the entire inner dict
    for that path.  A global ``maxsize`` caps the total number of entries
    across all registered functions to prevent unbounded memory growth.
    """

    def __init__(self, maxsize: int = 2048):
        self._lock = threading.Lock()
        self._stores: List[Dict[Path, Dict[tuple, Any]]] = []
        self._maxsize = maxsize
        self._total_entries = 0

    def cached(self, func: Callable) -> Callable:
        """Decorator -- equivalent to ``@lru_cache`` but with per-key eviction."""
        store: Dict[Path, Dict[tuple, Any]] = {}
        self._stores.append(store)

        def wrapper(*args, **kwargs):
            # The first positional arg is always the file path.
            file_path = args[0] if args else None
            resolved = file_path.resolve() if isinstance(file_path, Path) else None
            sub_key = (args[1:], tuple(sorted(kwargs.items())))
            with self._lock:
                bucket = store.get(resolved)
                if bucket is not None and sub_key in bucket:
                    return bucket[sub_key]
            # Compute outside the lock to avoid holding it during I/O.
            result = func(*args, **kwargs)
            with self._lock:
                if self._total_entries >= self._maxsize:
                    self._evict_oldest()
                bucket = store.setdefault(resolved, {})
                if sub_key not in bucket:
                    self._total_entries += 1
                bucket[sub_key] = result
            return result

        wrapper._store = store  # type: ignore[attr-defined]

        def _clear():
            with self._lock:
                n = sum(len(b) for b in store.values())
                store.clear()
                self._total_entries -= n

        wrapper.cache_clear = _clear  # type: ignore[attr-defined]
        return wrapper

    def _evict_oldest(self):
        """Drop roughly half the entries across all stores (called under lock)."""
        target = self._maxsize // 2
        evicted = 0
        for store in self._stores:
            paths_to_remove = []
            for path, bucket in store.items():
                evicted += len(bucket)
                paths_to_remove.append(path)
                if evicted >= target:
                    break
            for p in paths_to_remove:
                del store[p]
            if evicted >= target:
                break
        self._total_entries -= evicted

    def invalidate(self, file_path: Optional[Path] = None):
        """Drop cache entries.

        If *file_path* is given, only entries keyed by that resolved path
        are removed -- O(number of registered functions), safe to call from
        a worker thread without disturbing other threads' cached results.

        If *file_path* is ``None`` every entry in every registered store is
        cleared (equivalent to the old ``invalidate_read_caches()``).
        """
        with self._lock:
            if file_path is None:
                for store in self._stores:
                    store.clear()
                self._total_entries = 0
            else:
                resolved = file_path.resolve()
                for store in self._stores:
                    bucket = store.pop(resolved, None)
                    if bucket is not None:
                        self._total_entries -= len(bucket)


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
            evicted from the main ``FileCache``.  When ``None``, *all*
            cached entries are dropped (legacy full-clear behaviour).

    Note:
        Functions registered via ``register_cache`` (legacy ``lru_cache``
        decorators) are always fully cleared regardless of *file_path*,
        as ``lru_cache`` does not support per-key eviction.
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
