"""Shared utilities for builtin rules."""

import json
import re
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml
from ruamel.yaml import YAML as _RuamelYAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq


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
    """Find the 1-based line number of a top-level key in YAML frontmatter.

    Uses ruamel.yaml's round-trip parser for accurate line tracking
    that correctly handles quoted values, multiline strings, anchors, etc.
    """
    content = read_text(file_path)
    if content is None:
        return None
    fm_text, offset = _extract_frontmatter_text(content)
    if fm_text is None:
        return None
    return yaml_key_line(fm_text, key, top_level=True, line_offset=offset)


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


# ---------------------------------------------------------------------------
# Centralized YAML line-number utilities (ruamel.yaml round-trip)
# ---------------------------------------------------------------------------

_FRONTMATTER_TEXT_RE = re.compile(r"^---[ \t]*\n(.*?\n)---[ \t]*\n?", re.DOTALL)


def _extract_frontmatter_text(content: str) -> Tuple[Optional[str], int]:
    """Extract raw frontmatter YAML text and its line offset in the file.

    Returns ``(yaml_text, offset)`` where *offset* is the number of lines
    before the YAML content (i.e. the ``---`` line itself, so typically 1).
    Returns ``(None, 0)`` when no frontmatter is found.
    """
    m = _FRONTMATTER_TEXT_RE.match(content)
    if not m:
        return None, 0
    # The opening --- is on line 1, so the YAML content starts at line 2.
    return m.group(1), 1


def _ruamel_load(text: str) -> Any:
    """Parse YAML text with ruamel.yaml round-trip loader.

    Returns the parsed data (CommentedMap/CommentedSeq) preserving line
    numbers, or ``None`` on parse failure.
    """
    ry = _RuamelYAML()
    ry.preserve_quotes = True
    try:
        return ry.load(text)
    except Exception:
        return None


def yaml_key_line(
    text: str,
    key: str,
    *,
    top_level: bool = False,
    line_offset: int = 0,
) -> Optional[int]:
    """Find the 1-based line number of the first occurrence of *key*.

    Args:
        text: Raw YAML text to parse.
        key: Key name to search for.
        top_level: If ``True``, only search top-level keys.
        line_offset: Added to the 0-based ruamel line to produce a
            1-based file line (e.g. 1 for frontmatter after ``---``).

    Returns:
        The 1-based line number, or ``None`` if *key* is not found.
    """
    data = _ruamel_load(text)
    if data is None:
        return None

    if top_level:
        if isinstance(data, CommentedMap) and key in data:
            return data.lc.key(key)[0] + 1 + line_offset
        return None

    # Depth-first search for first occurrence
    result = _find_key_dfs(data, key)
    if result is not None:
        return result + 1 + line_offset
    return None


def yaml_key_lines(text: str, key: str, *, line_offset: int = 0) -> List[int]:
    """Find 1-based line numbers of ALL occurrences of *key* in the YAML.

    Performs a depth-first traversal, returning every mapping key that
    matches *key* in document order.
    """
    data = _ruamel_load(text)
    if data is None:
        return []
    results: List[int] = []
    _collect_key_lines(data, key, results)
    return [line0 + 1 + line_offset for line0 in results]


def yaml_line_map(text: str, *, line_offset: int = 0) -> Dict[str, int]:
    """Build a flat map of key names to 1-based line numbers.

    Traverses the full YAML tree.  When the same key name appears at
    multiple levels, the *last* occurrence wins (matching the old regex
    behaviour which also returned the last match for a flat scan).
    """
    data = _ruamel_load(text)
    if data is None:
        return {}
    result: Dict[str, int] = {}
    _build_line_map(data, result, line_offset)
    return result


def yaml_node_line(
    text: str,
    path: str,
    *,
    line_offset: int = 0,
) -> Optional[int]:
    """Find the 1-based line number for a dotted-path key.

    The path may include list indices, e.g. ``reviews.path_instructions[0].instructions``.

    Args:
        text: Raw YAML text.
        path: Dotted key path, e.g. ``"metadata.openclaw.os"``.
        line_offset: Added to produce a 1-based file line.

    Returns:
        1-based line number, or ``None`` if the path does not exist.
    """
    data = _ruamel_load(text)
    if data is None:
        return None
    return _resolve_path_line(data, path, line_offset)


def yaml_key_line_after(
    text: str,
    key: str,
    after_line: int,
    *,
    line_offset: int = 0,
) -> Optional[int]:
    """Find the first occurrence of *key* whose line number is > *after_line*.

    Both *after_line* and the returned value are 1-based file line numbers.
    """
    all_lines = yaml_key_lines(text, key, line_offset=line_offset)
    for line in all_lines:
        if line > after_line:
            return line
    return None


def yaml_nth_key_line(
    text: str,
    key: str,
    n: int,
    *,
    line_offset: int = 0,
) -> Optional[int]:
    """Find the 1-based line of the *n*-th (0-based) occurrence of *key*."""
    all_lines = yaml_key_lines(text, key, line_offset=line_offset)
    if n < len(all_lines):
        return all_lines[n]
    return None


def yaml_nth_list_item_key_line(
    text: str,
    key: str,
    n: int,
    *,
    after_line: int = 0,
    line_offset: int = 0,
) -> Optional[int]:
    """Find the *n*-th (0-based) list-item key after *after_line*.

    In YAML, list items look like ``- key: value``.  This function finds
    keys that are the *first* key of a mapping inside a sequence.
    """
    data = _ruamel_load(text)
    if data is None:
        return None
    results: List[int] = []
    _collect_list_item_key_lines(data, key, results)
    # Filter to those after after_line and convert to 1-based
    filtered = [
        line0 + 1 + line_offset for line0 in results if line0 + 1 + line_offset > after_line
    ]
    if n < len(filtered):
        return filtered[n]
    return None


# ---------------------------------------------------------------------------
# Internal tree-walking helpers
# ---------------------------------------------------------------------------


def _find_key_dfs(node: Any, key: str) -> Optional[int]:
    """Return the 0-based line of the first occurrence of *key* (DFS)."""
    if isinstance(node, CommentedMap):
        if key in node:
            return node.lc.key(key)[0]
        for v in node.values():
            result = _find_key_dfs(v, key)
            if result is not None:
                return result
    elif isinstance(node, (CommentedSeq, list)):
        for item in node:
            result = _find_key_dfs(item, key)
            if result is not None:
                return result
    return None


def _collect_key_lines(node: Any, key: str, results: List[int]) -> None:
    """Collect 0-based lines of every occurrence of *key* (DFS, document order)."""
    if isinstance(node, CommentedMap):
        for k in node:
            if k == key:
                results.append(node.lc.key(k)[0])
        # Recurse into values after collecting keys at this level
        for v in node.values():
            _collect_key_lines(v, key, results)
    elif isinstance(node, (CommentedSeq, list)):
        for item in node:
            _collect_key_lines(item, key, results)


def _build_line_map(node: Any, result: Dict[str, int], line_offset: int) -> None:
    """Populate *result* mapping every key name to its 1-based line."""
    if isinstance(node, CommentedMap):
        for k in node:
            result[k] = node.lc.key(k)[0] + 1 + line_offset
            _build_line_map(node[k], result, line_offset)
    elif isinstance(node, (CommentedSeq, list)):
        for item in node:
            _build_line_map(item, result, line_offset)


def _collect_list_item_key_lines(node: Any, key: str, results: List[int]) -> None:
    """Collect 0-based lines of *key* when it appears as first key in a list item."""
    if isinstance(node, CommentedMap):
        for v in node.values():
            _collect_list_item_key_lines(v, key, results)
    elif isinstance(node, (CommentedSeq, list)):
        for item in node:
            if isinstance(item, CommentedMap):
                # Check if the first key of this list-item mapping matches
                keys = list(item.keys())
                if keys and keys[0] == key:
                    results.append(item.lc.key(key)[0])
                # Also recurse into the values of this mapping
                for v in item.values():
                    _collect_list_item_key_lines(v, key, results)
            elif isinstance(item, (CommentedSeq, list)):
                _collect_list_item_key_lines(item, key, results)


def _resolve_path_line(node: Any, path: str, line_offset: int) -> Optional[int]:
    """Resolve a dotted path like ``a.b[0].c`` and return the 1-based line."""
    import re as _re

    parts = _re.split(r"\.|(?=\[)", path)
    current = node
    last_key: Optional[str] = None
    last_map: Any = None

    for part in parts:
        if not part:
            continue
        idx_match = _re.fullmatch(r"\[(\d+)\]", part)
        if idx_match:
            idx = int(idx_match.group(1))
            if not isinstance(current, (CommentedSeq, list)) or idx >= len(current):
                return None
            current = current[idx]
        else:
            if not isinstance(current, CommentedMap) or part not in current:
                return None
            last_map = current
            last_key = part
            current = current[part]

    if last_map is not None and last_key is not None:
        return last_map.lc.key(last_key)[0] + 1 + line_offset
    return None
