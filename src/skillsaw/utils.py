"""Shared utilities for builtin rules."""

import json
import math
import os
import re
import secrets
import stat
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, NoReturn, Optional, Tuple

import yaml
from ruamel.yaml import YAML as _RuamelYAML
from ruamel.yaml import YAMLError as _RuamelYAMLError
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from skillsaw.paths import safe_is_symlink, safe_resolve


def _atomic_destination(path: Path, root: Path) -> Tuple[Path, Path]:
    """Return a resolved root and lexical relative destination, or fail closed."""
    resolved_root = safe_resolve(root)
    lexical_path = Path(os.path.abspath(path))
    if resolved_root is None:
        raise OSError(f"Could not resolve atomic-write root: {root}")
    try:
        relative = lexical_path.relative_to(resolved_root)
    except ValueError as exc:
        raise OSError(f"Atomic-write destination escapes root: {path}") from exc
    if not relative.name:
        raise OSError(f"Atomic-write destination is not a file: {path}")

    current = resolved_root
    for component in relative.parent.parts:
        current /= component
        if safe_is_symlink(current):
            raise OSError(f"Refusing to write through symlinked directory: {current}")
    resolved_path = safe_resolve(lexical_path)
    if resolved_path is None or not resolved_path.is_relative_to(resolved_root):
        raise OSError(f"Atomic-write destination escapes root: {path}")
    return resolved_root, relative


def _supports_anchored_atomic_write() -> bool:
    required = (os.open, os.rename, os.stat, os.unlink)
    return (
        hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and all(function in os.supports_dir_fd for function in required)
    )


def _open_atomic_parent(path: Path, root: Path) -> Tuple[int, str]:
    """Open the destination parent without following repository symlinks."""
    resolved_root, relative = _atomic_destination(path, root)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC

    directory_fd = os.open(resolved_root, flags)
    try:
        for component in relative.parent.parts:
            child_fd = os.open(component, flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = child_fd
    except BaseException:
        os.close(directory_fd)
        raise
    return directory_fd, relative.name


def mkdir_parents_anchored(directory: Path, *, root: Path) -> None:
    """Create a contained directory tree without following symlinked parents.

    Descriptor-capable platforms pin each existing or newly created component
    before descending into it. Other platforms validate containment and reject
    symlinks immediately before and after their native ``mkdir`` operation.
    """
    anchor = directory / ".skillsaw-directory-anchor"
    resolved_root, anchor_relative = _atomic_destination(anchor, root)
    relative = anchor_relative.parent
    if not relative.parts:
        return

    supports_anchored_mkdir = (
        _supports_anchored_atomic_write()
        and os.mkdir in os.supports_dir_fd
        and os.open in os.supports_dir_fd
    )
    if not supports_anchored_mkdir:
        directory.mkdir(parents=True, exist_ok=True)
        _atomic_destination(anchor, root)
        if safe_is_symlink(directory) or not directory.is_dir():
            raise OSError(f"Refusing to use symlinked directory: {directory}")
        return

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    directory_fd = os.open(resolved_root, flags)
    try:
        for component in relative.parts:
            try:
                child_fd = os.open(component, flags, dir_fd=directory_fd)
            except FileNotFoundError:
                try:
                    os.mkdir(component, mode=0o755, dir_fd=directory_fd)
                except FileExistsError:
                    # Another process created the component after our open.
                    # The no-follow open below still validates what won.
                    pass
                child_fd = os.open(component, flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = child_fd
    finally:
        os.close(directory_fd)


def rename_path_anchored(source: Path, destination: Path, *, root: Path) -> None:
    """Rename a repository file without following source or destination parents.

    Both parent directories stay pinned by descriptors for the rename, closing
    the gap where a repository-controlled directory can be replaced by a
    symlink after a lexical containment check. Existing destinations are only
    accepted for case-only renames of the same inode. Platforms without
    descriptor-relative rename support use contained, symlink-rejecting path
    validation immediately before their native rename operation.
    """
    if not _supports_anchored_atomic_write():
        source_root, source_relative = _atomic_destination(source, root)
        destination_root, destination_relative = _atomic_destination(destination, root)

        checked_source = source_root / source_relative
        checked_destination = destination_root / destination_relative
        source_stat = checked_source.lstat()
        if stat.S_ISLNK(source_stat.st_mode):
            raise OSError(f"Refusing to rename symlink: {source}")
        try:
            destination_stat = checked_destination.lstat()
        except FileNotFoundError:
            pass
        else:
            if stat.S_ISLNK(destination_stat.st_mode):
                raise OSError(f"Refusing to rename over symlink: {destination}")
            source_identity = (source_stat.st_dev, source_stat.st_ino)
            destination_identity = (destination_stat.st_dev, destination_stat.st_ino)
            if destination_identity != source_identity:
                raise FileExistsError(f"Rename destination already exists: {destination}")

        checked_source.rename(checked_destination)
        return

    source_fd, source_name = _open_atomic_parent(source, root)
    destination_fd = -1
    try:
        destination_fd, destination_name = _open_atomic_parent(destination, root)
        source_stat = os.stat(source_name, dir_fd=source_fd, follow_symlinks=False)
        if stat.S_ISLNK(source_stat.st_mode):
            raise OSError(f"Refusing to rename symlink: {source}")

        try:
            destination_stat = os.stat(
                destination_name,
                dir_fd=destination_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            pass
        else:
            if stat.S_ISLNK(destination_stat.st_mode):
                raise OSError(f"Refusing to rename over symlink: {destination}")
            source_identity = (source_stat.st_dev, source_stat.st_ino)
            destination_identity = (destination_stat.st_dev, destination_stat.st_ino)
            if destination_identity != source_identity:
                raise FileExistsError(f"Rename destination already exists: {destination}")

        os.rename(
            source_name,
            destination_name,
            src_dir_fd=source_fd,
            dst_dir_fd=destination_fd,
        )
    finally:
        if destination_fd >= 0:
            os.close(destination_fd)
        os.close(source_fd)


def write_bytes_atomic(path: Path, content: bytes, *, root: Optional[Path] = None) -> None:
    """Atomically replace *path* without following a file-level symlink.

    Generated artifacts use predictable names inside repositories being
    inspected. A checked-in symlink at one of those names must never turn a
    lint command into an arbitrary-file overwrite. The explicit refusal gives
    callers a useful error; atomic replacement closes the check/write race by
    replacing a link that appears after the check instead of following it.
    Existing permissions are preserved; new files use private mode ``0600``.
    When *root* is provided, every destination parent is opened relative to an
    anchored root directory without following symlinks.
    """
    if safe_is_symlink(path):
        raise OSError(f"Refusing to write through symlink: {path}")

    if root is not None and _supports_anchored_atomic_write():
        parent_fd, destination_name = _open_atomic_parent(path, root)
        temporary_name = ""
        fd = -1
        try:
            existing_mode = None
            try:
                destination_stat = os.stat(
                    destination_name, dir_fd=parent_fd, follow_symlinks=False
                )
                if stat.S_ISLNK(destination_stat.st_mode):
                    raise OSError(f"Refusing to write through symlink: {path}")
                existing_mode = stat.S_IMODE(destination_stat.st_mode)
            except FileNotFoundError:
                pass

            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_CLOEXEC"):
                flags |= os.O_CLOEXEC
            for _attempt in range(100):
                temporary_name = f".{destination_name}.{secrets.token_hex(8)}"
                try:
                    fd = os.open(temporary_name, flags, 0o600, dir_fd=parent_fd)
                    break
                except FileExistsError:
                    continue
            else:
                raise FileExistsError(f"Could not allocate temporary file beside {path}")

            if existing_mode is not None:
                os.fchmod(fd, existing_mode)
            stream = os.fdopen(fd, "wb")
            fd = -1
            with stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
                opened_stat = os.fstat(stream.fileno())
            temporary_stat = os.stat(temporary_name, dir_fd=parent_fd, follow_symlinks=False)
            if (temporary_stat.st_dev, temporary_stat.st_ino) != (
                opened_stat.st_dev,
                opened_stat.st_ino,
            ):
                raise OSError(f"Atomic-write temporary file was replaced: {path}")
            os.rename(
                temporary_name,
                destination_name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
            )
            temporary_name = ""
            return
        finally:
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
            if temporary_name:
                try:
                    os.unlink(temporary_name, dir_fd=parent_fd)
                except OSError:
                    pass
            os.close(parent_fd)

    if root is not None:
        _atomic_destination(path, root)

    existing_mode = None
    try:
        existing_mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        pass

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    for _attempt in range(100):
        temporary = path.parent / f".{path.name}.{secrets.token_hex(8)}"
        try:
            fd = os.open(temporary, flags, 0o600)
            break
        except FileExistsError:
            continue
    else:
        raise FileExistsError(f"Could not allocate temporary file beside {path}")
    try:
        if existing_mode is not None:
            if hasattr(os, "fchmod"):
                os.fchmod(fd, existing_mode)
            else:  # Python < 3.13 on Windows
                os.chmod(temporary, existing_mode)
        stream = os.fdopen(fd, "wb")
        fd = -1  # os.fdopen transferred ownership to stream.
        with stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if root is not None:
            _atomic_destination(path, root)
        os.replace(temporary, path)
    except BaseException:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


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
            try:
                resolved = (
                    (safe_resolve(file_path) or file_path) if isinstance(file_path, Path) else None
                )
            except (OSError, RuntimeError, ValueError):
                # Symlink loop or embedded NUL: raising here aborts the
                # whole lint from a cache key lookup, while the wrapped
                # reader already diagnoses unreadable input. Key on the
                # unresolved path — that only loses alias deduplication.
                resolved = file_path
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
                resolved = safe_resolve(file_path) or file_path
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
    """Cached file read. Returns None on I/O or encoding errors.

    Uses ``utf-8-sig`` so a leading UTF-8 BOM is stripped from the returned
    text — otherwise the stray ``\\ufeff`` prevents ``^---`` frontmatter
    detection and every ``startswith("---")`` check.  Newlines are left in
    universal-newline form (CRLF collapses to ``\\n`` in the returned text);
    the original line-ending style is restored at write time by
    :func:`write_text_preserving`.
    """
    try:
        return file_path.read_text(encoding="utf-8-sig")
    except (IOError, UnicodeDecodeError):
        return None


def write_text_preserving(file_path: Path, content: str, *, root: Optional[Path] = None) -> None:
    """Write *content*, restoring the file's original BOM and line endings.

    ``read_text`` normalizes a file to BOM-free, ``\\n``-delimited text for
    analysis, so ``content`` (spliced from that normalized text) is always
    LF and BOM-free.  A naive ``write_text`` would therefore silently rewrite
    a CRLF file to LF and drop a UTF-8 BOM on every autofix.  This reads the
    on-disk bytes *before* overwriting, detects the original BOM and dominant
    line ending, and re-applies them so an autofix only changes the span it
    meant to.
    """
    try:
        original = file_path.read_bytes()
    except OSError:
        original = b""

    has_bom = original.startswith(b"\xef\xbb\xbf")
    sample = original[3:] if has_bom else original
    # Use the DOMINANT line ending: a single stray CRLF in an otherwise-LF
    # file must not flip every line to CRLF (and vice versa).  Ties and
    # lone-CR (classic Mac) files normalize to LF.
    crlf_count = sample.count(b"\r\n")
    bare_lf_count = sample.count(b"\n") - crlf_count
    uses_crlf = crlf_count > bare_lf_count

    # Normalize whatever the caller produced back to BOM-free LF first, so
    # re-applying the original shape is idempotent even when a fix path read
    # the file with plain utf-8 (leaving a BOM) or newline="" (leaving CRLF).
    normalized = content.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if uses_crlf:
        normalized = normalized.replace("\n", "\r\n")

    data = normalized.encode("utf-8")
    if has_bom:
        data = b"\xef\xbb\xbf" + data
    write_bytes_atomic(file_path, data, root=root)


# Reported instead of the traceback when a document nests past the
# interpreter's stack limit.
_TOO_DEEP = "Nesting too deep to parse"


@_file_cache.cached
def read_json(file_path: Path) -> Tuple[Optional[object], Optional[str]]:
    """Cached JSON file read. Returns (data, error)."""
    content = read_text(file_path)
    if content is None:
        return None, f"Failed to read {file_path.name}"
    try:
        return json.loads(content), None
    except ValueError as e:
        # ValueError, not just its JSONDecodeError subclass: on 3.11+ an
        # integer literal past the interpreter's digit limit raises bare
        # ValueError, and discovery calls this while RepositoryContext is
        # still being constructed — letting it escape aborts the CLI.
        return None, str(e)
    except RecursionError:
        # ``json`` parses nested containers recursively. Discovery reads
        # manifests during RepositoryContext construction, outside the
        # rule-execution-error guard, so letting this propagate aborts the
        # whole lint with a traceback.
        return None, _TOO_DEEP


# A compiled output carries a stamp saying so. Matched forms: the generic
# "generated by ... do not edit" wording, and APM's actual header, which is
# only '<!-- Generated by APM CLI from .apm/ primitives -->' — no "do not
# edit" text anywhere in the file.
_GENERATED_MARKER = re.compile(
    r"generated by .*(?:do not edit|don't edit)|do not edit manually|generated by apm cli",
    re.IGNORECASE,
)


def has_generated_marker(text: Optional[str]) -> bool:
    """Whether *text* mentions anywhere that it is a compiled output.

    Deliberately lenient, and paired with a strict counterpart below. The
    caller that only *suppresses* a finding can afford to be wrong — a
    generated-looking file skipped by ``content-instruction-drift`` costs
    one missed comparison, and a footer saying "generated by X, do not
    edit manually" is a real stamp that a header check would miss.
    """
    return bool(text) and _GENERATED_MARKER.search(text) is not None


#: The exact first line APM writes into every file it compiles. Matched
#: literally, not by pattern: any phrase heuristic also matches authored
#: prose *about* generated files (and in Markdown a comment-ish line test
#: matches every `#` heading), and a false positive here drops a real file
#: out of the lint tree entirely.
APM_GENERATED_HEADER = "<!-- Generated by APM CLI from .apm/ primitives -->"

#: How far in the banner may sit. APM writes it first; a stray blank line or
#: a leading BOM should not defeat the check.
_GENERATED_HEADER_LINES = 5


def has_apm_generated_header(text: Optional[str]) -> bool:
    """Whether *text* opens with APM's own compiled-output banner.

    The strict counterpart to :func:`has_generated_marker`, for the one
    caller whose false positive is expensive rather than cheap. The lint
    tree uses this to drop APM's compiled Copilot file; being wrong there
    removes the file from every content, security and budget rule, so the
    evidence has to be something prose cannot accidentally produce.

    An exact line, not a pattern. If APM ever changes its banner this stops
    matching, and the failure is that the compiled copy gets linted
    alongside its source — duplicate findings, which are visible and
    annoying. The other direction silently deletes a file from the lint,
    and that is the mistake this function exists to stop making.
    """
    if not text:
        return False
    head = text.lstrip("\ufeff").split("\n", _GENERATED_HEADER_LINES)
    return any(line.strip() == APM_GENERATED_HEADER for line in head[:_GENERATED_HEADER_LINES])


def is_finite_number(value: Any) -> bool:
    """Whether *value* is a real, finite JSON number.

    ``bool`` is excluded — it is an ``int`` subclass, and ``timeout: true``
    is not a duration however permissively you read it.

    ``int`` is answered without touching ``math.isfinite``: a Python int is
    always finite, and handing a big one to a function that takes a float
    raises ``OverflowError``. JSON has no bound on integer literals, so a
    400-digit ``timeout`` is a document any host will parse — and the
    conversion would take down every check in the rule that met it, losing
    that rule's findings for the whole repository.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if isinstance(value, int):
        return True
    return math.isfinite(value)


def _reject_non_finite(token: str) -> NoReturn:
    raise ValueError(f"{token} is not valid JSON")


@_file_cache.cached
def read_json_strict(file_path: Path) -> Tuple[Optional[object], Optional[str]]:
    """Like :func:`read_json`, but rejecting Python's non-finite extension.

    ``json.loads`` accepts the bare tokens ``NaN``, ``Infinity`` and
    ``-Infinity`` anywhere a number is allowed. No JSON host does: Node
    throws on the whole document, so a config carrying one is dead on
    arrival for the tool that reads it while skillsaw reports it clean.

    Kept separate from :func:`read_json` rather than folded into it because
    discovery reads manifests through that function — tightening it there
    would turn a plugin whose ``plugin.json`` holds such a token from
    "discovered, one bad value" into "not discovered at all", dropping the
    plugin's whole subtree from the lint. Blocks opt in with
    ``strict_json``.
    """
    content = read_text(file_path)
    if content is None:
        return None, f"Failed to read {file_path.name}"
    try:
        return json.loads(content, parse_constant=_reject_non_finite), None
    except ValueError as e:
        # Same rationale as read_json: bare ValueError, not just the
        # JSONDecodeError subclass.
        return None, str(e)
    except RecursionError:
        return None, _TOO_DEEP


@_file_cache.cached
def read_yaml(file_path: Path) -> Tuple[Optional[object], Optional[str]]:
    """Cached YAML file read. Returns (data, error)."""
    content = read_text(file_path)
    if content is None:
        return None, f"Failed to read {file_path.name}"
    try:
        return yaml.safe_load(content), None
    except yaml.YAMLError as e:
        return None, str(e)
    except ValueError as e:
        # PyYAML can surface parser-adjacent failures as a bare ValueError;
        # Python's integer-string digit limit is one example. Treat it like
        # every other invalid document instead of aborting tree construction.
        return None, str(e)
    except RecursionError:
        # Same hazard as read_json — see the note there.
        return None, _TOO_DEEP


@_file_cache.cached
def read_yaml_commented(
    file_path: Path,
) -> Tuple[Any, Optional[str], Optional[int]]:
    """Cached YAML read preserving line-number info via ruamel.yaml.

    Returns ``(data, error_msg, error_line)`` where *data* is a
    ``CommentedMap`` / ``CommentedSeq`` supporting ``.lc.key()`` and
    ``.lc.item()`` for line-number lookups.
    """
    content = read_text(file_path)
    if content is None:
        return None, f"Failed to read {file_path.name}", None
    ry = _RuamelYAML()
    ry.preserve_quotes = True
    try:
        data = ry.load(content)
        return data, None, None
    except _RuamelYAMLError as e:
        line = None
        if hasattr(e, "problem_mark") and e.problem_mark is not None:
            line = e.problem_mark.line + 1
        return None, str(e), line
    except ValueError as e:
        return None, str(e), None
    except RecursionError:
        return None, _TOO_DEEP, None


def commented_key_line(node: Any, key: str) -> Optional[int]:
    """Get the 1-based line number of *key* in a ruamel ``CommentedMap``."""
    if isinstance(node, CommentedMap) and key in node:
        try:
            pos = node.lc.key(key)
        except KeyError:
            # A value inherited through a YAML merge key (``<<: *anchor``)
            # is visible to ``in``/``get`` but has no local position —
            # omit the line rather than crash the rule.
            return None
        if pos is None:
            # When a map's keys ALL come from a merge, ruamel leaves
            # ``lc.data`` unset and ``lc.key()`` returns None instead of
            # raising — same answer: no local position, no line.
            return None
        return pos[0] + 1
    return None


def commented_item_line(node: Any, index: int) -> Optional[int]:
    """Get the 1-based line number of item *index* in a ruamel ``CommentedSeq``."""
    if isinstance(node, CommentedSeq) and index < len(node):
        return node.lc.item(index)[0] + 1
    return None


def commented_root_line(node: Any) -> Optional[int]:
    """Get the 1-based line number of the document root, when ruamel kept one.

    Plain scalars carry no position, so the line is ``None`` for them —
    callers must omit the line rather than fabricate one.
    """
    lc = getattr(node, "lc", None)
    if lc is not None and lc.line is not None:
        return lc.line + 1
    return None


def _fast_top_level_key_nodes(
    text: str,
) -> Optional[Dict[str, Tuple[yaml.Node, yaml.Node]]]:
    """Map top-level mapping keys to their ``(key_node, value_node)`` pair
    using PyYAML's composer (libyaml-backed when available).

    The nodes carry ``start_mark`` / ``end_mark`` positions, so callers can
    locate the exact character span a key and its value occupy.  Returns
    ``None`` when the document needs the ruamel fallback to preserve exact
    behavior: parse errors, non-string keys, or duplicate keys (which
    ruamel rejects).
    """
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    try:
        node = yaml.compose(text, Loader=loader)
    except yaml.YAMLError:
        return None
    if node is None or not isinstance(node, yaml.MappingNode):
        return {}
    result: Dict[str, Tuple[yaml.Node, yaml.Node]] = {}
    for key_node, value_node in node.value:
        if not isinstance(key_node, yaml.ScalarNode) or key_node.tag != "tag:yaml.org,2002:str":
            return None
        if key_node.value in result:
            return None
        result[key_node.value] = (key_node, value_node)
    return result


def _fast_top_level_key_lines(text: str) -> Optional[Dict[str, int]]:
    """Map top-level mapping keys to 0-based lines using PyYAML's composer.

    Much faster than a ruamel round-trip parse (libyaml-backed when
    available).  Returns ``None`` when the document needs the ruamel
    fallback to preserve exact behavior: parse errors, non-string keys,
    or duplicate keys (which ruamel rejects).
    """
    nodes = _fast_top_level_key_nodes(text)
    if nodes is None:
        return None
    return {key: key_node.start_mark.line for key, (key_node, _value) in nodes.items()}


@_file_cache.cached
def frontmatter_line_map_top_level(file_path: Path) -> Dict[str, int]:
    """Map every top-level frontmatter key to its 1-based file line.

    Parses the frontmatter once per file (cached), so per-key lookups via
    :func:`frontmatter_key_line` are dictionary hits.
    """
    content = read_text(file_path)
    if content is None:
        return {}
    fm_text, offset = _extract_frontmatter_text(content)
    if fm_text is None:
        return {}
    fast = _fast_top_level_key_lines(fm_text)
    if fast is not None:
        return {key: line0 + 1 + offset for key, line0 in fast.items()}
    # Exotic frontmatter (non-string keys, duplicates, parse errors):
    # ruamel round-trip parse, matching the pre-fast-path behavior.
    data = _ruamel_load(fm_text)
    if not isinstance(data, CommentedMap):
        return {}
    return {key: data.lc.key(key)[0] + 1 + offset for key in data}


def frontmatter_key_line(file_path: Path, key: str) -> Optional[int]:
    """Find the 1-based line number of a top-level key in YAML frontmatter."""
    return frontmatter_line_map_top_level(file_path).get(key)


# The single source of truth for frontmatter block matching.  Tolerates CRLF
# line endings (previously only the skills fix path did).
_FRONTMATTER_RE = re.compile(r"^---[ \t]*\r?\n(.*?\r?\n)---[ \t]*\r?(?:\n|\Z)", re.DOTALL)
FRONTMATTER_RE = _FRONTMATTER_RE

# Variant that also matches an empty frontmatter block (``---\n---``); the
# group is always present but may be the empty string.
FRONTMATTER_RE_EMPTY_OK = re.compile(
    r"^---[ \t]*\r?\n((?:.*?\r?\n)?)---[ \t]*\r?(?:\n|$)", re.DOTALL
)


def frontmatter_text(content: str) -> Optional[str]:
    """Return the raw YAML text between the ``---`` delimiters, or ``None``."""
    m = _FRONTMATTER_RE.match(content)
    return m.group(1) if m else None


def _frontmatter_newline(matched: str) -> str:
    return "\r\n" if "\r\n" in matched else "\n"


def insert_frontmatter_fields(content: str, additions: List[str]) -> Optional[str]:
    """Insert field lines just before the closing ``---`` of the frontmatter.

    Returns the new content, or ``None`` when *content* has no parseable
    frontmatter block.
    """
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return None
    newline = _frontmatter_newline(m.group(0))
    insert = "".join(line + newline for line in additions)
    close_offset = m.end(1)
    return content[:close_offset] + insert + content[close_offset:]


def prepend_frontmatter_fields(content: str, additions: List[str]) -> Optional[str]:
    """Insert field lines right after the opening ``---`` of the frontmatter."""
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return None
    newline = _frontmatter_newline(m.group(0))
    insert = "".join(line + newline for line in additions)
    return content[: m.start(1)] + insert + content[m.start(1) :]


def replace_frontmatter_field(content: str, key: str, replacement_line: str) -> Optional[str]:
    """Replace an existing top-level ``key:`` field inside the frontmatter.

    The true top-level key is located with the same libyaml-backed composer
    that powers :func:`frontmatter_key_line` — a bare ``^key:`` regex also
    matches column-0 *continuation* lines of another structure (e.g. the
    second line of ``metadata: {tags: [x],\\nname: legacy-tag}``) and
    replacing those corrupts previously-valid YAML (issue: agentskill-valid
    SAFE-fix corruption).

    Returns:
        - the new content, with the key line **and its full value span**
          replaced by *replacement_line* (a value continuing on following
          lines — flow collection, block scalar, multi-line plain scalar —
          is collapsed so no orphaned continuation lines remain);
        - ``None`` when *content* has no parseable frontmatter block or no
          genuine top-level ``key`` to replace (callers may then safely
          insert the field instead);
        - *content* unchanged when the key exists but the span cannot be
          verified (exotic frontmatter: duplicate keys, non-string keys,
          flow-style or quoted key lines) — a no-op beats corruption.
    """
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return None
    fm_text = m.group(1)
    key_re = re.compile(rf"^{re.escape(key)}[ \t]*:[^\r\n]*", re.MULTILINE)
    nodes = _fast_top_level_key_nodes(fm_text)
    if nodes is None:
        # Exotic frontmatter (duplicate keys, non-string keys, parse error):
        # fall back to ruamel for key membership only.
        data = _ruamel_load(fm_text)
        if isinstance(data, CommentedMap):
            if key not in data:
                return None
        elif key_re.search(fm_text) is None:
            # Undeterminable structure and not even a key-shaped line: there
            # is nothing to replace.
            return None
        # Key present (or structure undeterminable): a blind line splice
        # could hit a continuation line, so leave the content untouched.
        return content
    if key not in nodes:
        # Any regex hit would be a continuation line of another structure,
        # not a top-level key.
        return None
    key_node, value_node = nodes[key]
    if key_node.start_mark.column != 0:
        # Flow-style top-level mapping ({key: ...}): no key *line* to splice.
        return content

    # 0-based offsets of each line start within fm_text (fm_text always ends
    # with a newline, so line N's start exists for every mark line N).
    line_starts = [0]
    idx = fm_text.find("\n")
    while idx != -1:
        line_starts.append(idx + 1)
        idx = fm_text.find("\n", idx + 1)

    key_line = key_node.start_mark.line
    if key_line >= len(line_starts):
        return content
    line_start = line_starts[key_line]
    km = key_re.match(fm_text, line_start)
    if km is None:
        # Quoted or otherwise decorated key line the callers' replacement
        # format does not cover.
        return content

    if value_node.end_mark.line <= key_line:
        # Single-line inline value (or empty/null value): replace just the
        # key line, preserving the original line ending.
        start = m.start(1) + km.start()
        end = m.start(1) + km.end()
        return content[:start] + replacement_line + content[end:]

    # Multi-line value: replace the whole span from the key line through the
    # value's end mark so no orphaned continuation lines remain.
    end_line = value_node.end_mark.line
    end_col = value_node.end_mark.column
    if end_line >= len(line_starts):
        return content
    end_off = line_starts[end_line] + end_col
    if end_off > len(fm_text):
        return content
    replacement = replacement_line
    if end_col == 0:
        # The value consumed its final line break (block scalars end at the
        # start of the following line); restore the newline.
        replacement += _frontmatter_newline(m.group(0))
    start = m.start(1) + line_start
    end = m.start(1) + end_off
    return content[:start] + replacement + content[end:]


def parse_frontmatter(content: str) -> Tuple[Optional[Dict[str, Any]], str, Optional[int]]:
    """Parse YAML frontmatter from markdown content.

    Returns (frontmatter_dict, body_after_frontmatter, error_line).
    ``error_line`` is set (1-indexed, relative to file) only on YAML parse errors.
    If no valid frontmatter is found, returns (None, original_content, error_line).
    """
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return None, content, None
    try:
        data = yaml.safe_load(m.group(1))
    except (yaml.YAMLError, ValueError, RecursionError) as e:
        error_line = None
        if hasattr(e, "problem_mark") and e.problem_mark is not None:
            error_line = e.problem_mark.line + 2  # +1 for 0-indexed, +1 for opening ---
        return None, content, error_line
    if not isinstance(data, dict):
        return None, content, None
    body = content[m.end() :]
    return data, body, None


def extract_section(content: str, heading: str, level: int = 2) -> str:
    """Extract content under a markdown heading, up to the next heading of same or higher level."""
    prefix = "#" * level
    # ``\r?`` must precede ``$``: in MULTILINE mode ``$`` matches before ``\n``,
    # so on a CRLF line the ``\r`` sits before that position and the heading
    # would never match if ``\r?`` came after ``$``.
    pattern = re.compile(
        rf"^{prefix}[ \t]+{re.escape(heading)}[ \t]*\r?$\n?(.*?)(?=^#{{{1},{level}}}[ \t]|\Z)",
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


def _extract_frontmatter_text(content: str) -> Tuple[Optional[str], int]:
    """Extract raw frontmatter YAML text and its line offset in the file.

    Returns ``(yaml_text, offset)`` where *offset* is the number of lines
    before the YAML content (i.e. the ``---`` line itself, so typically 1).
    Returns ``(None, 0)`` when no frontmatter is found.
    """
    m = _FRONTMATTER_RE.match(content)
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
    except _RuamelYAMLError:
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


def yaml_path_line_lookup(
    text: str,
    *,
    line_offset: int = 0,
) -> Callable[[str], Optional[int]]:
    """Parse *text* once and return a dotted-path -> line-number lookup.

    Equivalent to calling :func:`yaml_node_line` for each path, but the
    YAML is parsed a single time (ruamel round-trip parsing is expensive,
    so per-path parses must be avoided in rule loops).

    The returned callable accepts paths like
    ``metadata.openclaw.install[0].kind`` and returns the 1-based line
    number, or ``None`` when the path does not exist or its line cannot
    be determined (e.g. keys introduced via YAML merge keys).
    """
    data = _ruamel_load(text)

    def lookup(path: str) -> Optional[int]:
        if data is None:
            return None
        return _resolve_path_line(data, path, line_offset)

    return lookup


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
            try:
                result[k] = node.lc.key(k)[0] + 1 + line_offset
            except (KeyError, TypeError):
                # Keys introduced via YAML merge keys ('<<: *anchor') have no
                # position of their own in this mapping — ruamel raises
                # KeyError (or TypeError on some versions).  Skip them: an
                # omitted line number is correct, a crash is not.
                pass
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
    parts = re.split(r"\.|(?=\[)", path)
    current = node
    last_container: Any = None
    last_accessor: Any = None

    for part in parts:
        if not part:
            continue
        idx_match = re.fullmatch(r"\[(\d+)\]", part)
        if idx_match:
            idx = int(idx_match.group(1))
            if not isinstance(current, (CommentedSeq, list)) or idx >= len(current):
                return None
            last_container = current
            last_accessor = idx
            current = current[idx]
        else:
            if not isinstance(current, CommentedMap) or part not in current:
                return None
            last_container = current
            last_accessor = part
            current = current[part]

    try:
        if isinstance(last_container, CommentedMap) and isinstance(last_accessor, str):
            return last_container.lc.key(last_accessor)[0] + 1 + line_offset
        if isinstance(last_container, CommentedSeq) and isinstance(last_accessor, int):
            return last_container.lc.item(last_accessor)[0] + 1 + line_offset
    except (KeyError, TypeError):
        # Keys reachable only through a YAML merge key ('<<: *anchor') have
        # no position in this mapping — report no line rather than crash.
        return None
    return None
