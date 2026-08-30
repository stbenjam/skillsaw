"""Shared utilities for builtin rules."""

import json
import math
import os
import re
import secrets
import stat
import sys
from itertools import chain
import threading
import warnings
from pathlib import Path
from typing import Any, Callable, Dict, List, NoReturn, Optional, Set, Tuple

import yaml
from ruamel.yaml import YAML as _RuamelYAML
from ruamel.yaml import YAMLError as _RuamelYAMLError
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from skillsaw.paths import (
    _path_cost,
    clear_resolve_cache,
    resolve_generation,
    safe_is_symlink,
    safe_resolve,
)


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


#: Charged per container and per scalar an entry holds, on top of the text
#: it carries. A parsed document is mostly structure, and a flat estimate
#: for the whole of one lets a large document sit in the cache charged as
#: though it were small — which is how a byte budget stops holding.
_NODE_OVERHEAD_BYTES = 64

#: Cap on nodes walked while sizing one entry. The accounting runs on every
#: insertion, so it must cost less than what it protects.
_SIZE_WALK_LIMIT = 20_000

#: Returned when the size walk gives up at ``_SIZE_WALK_LIMIT``. A document
#: that large has no size the cache can trust, so it gets one no budget
#: admits — a concrete number would be admitted by any cache configured
#: above it, and then charged wrongly for as long as it stayed.
UNCACHEABLE_SIZE = -1

#: Charged on top of every entry's value and its key, for the machinery
#: between them: the per-path bucket dict, the sub-key tuple, and a slot in
#: each of the two dicts. Without it a repository of many small files is
#: bounded by nothing — 20,000 empty ``read_text`` results charge 20 KB
#: against a budget in the tens of megabytes while really holding 11 MiB.
#:
#: The key is measured separately rather than folded in here, because a
#: constant cannot stand for it: manifests supply the strings, so a
#: ``Path`` is not fixed-small. A 4 KB path retains 12x this, and one of
#: 400 short components 29x.
_ENTRY_OVERHEAD_BYTES = 512


#: Slot names per type, flattened over the MRO. The lookup below runs once
#: per container in a walk that runs on every cache insertion, and almost
#: every type it sees declares no slots at all — resolving that to an empty
#: tuple once per type keeps the common case a single dict hit. Keyed by
#: type objects, of which a process loads a bounded number.
_SLOT_NAMES: Dict[type, Tuple[str, ...]] = {}


def _slot_names(klass: type) -> Tuple[str, ...]:
    """Every ``__slots__`` name *klass* inherits, resolved once per type."""
    names = _SLOT_NAMES.get(klass)
    if names is None:
        names = []
        for base in klass.__mro__:
            declared = base.__dict__.get("__slots__", ())
            # ``__slots__ = "_yaml_anchor"`` is legal and means one slot of
            # that name. Iterating the string yields its characters, so a
            # class declaring it this way — every ruamel ``ScalarString``
            # does — would otherwise contribute no slots at all.
            if isinstance(declared, str):
                declared = (declared,)
            names.extend(declared)
        names = tuple(names)
        _SLOT_NAMES[klass] = names
    return names


def _push_attributes(node: Any, stack: List[Any]) -> None:
    """Queue whatever *node* holds in attributes rather than in items.

    This is where ruamel keeps the half of a commented document that has
    no key or value to be found under: comment tokens hang off ``.ca``,
    beside the mapping rather than inside it, so a comment-heavy config
    can retain several times what its visible keys and values measure.
    Both storage forms are needed: ruamel's containers put ``.ca`` in a
    ``__slots__`` entry and their line info in ``__dict__``.

    A ``CommentedMap`` is a ``dict``, so the container branches have to
    ask as well; reaching this only from the scalar tail would walk right
    past every one of them.
    """
    attributes = getattr(node, "__dict__", None)
    if attributes:
        stack.append(attributes)
    for slot in _slot_names(type(node)):
        held = getattr(node, slot, None)
        if held is not None:
            stack.append(held)


def _remember(node: Any, visited: Set[int], alive: List[Any]) -> None:
    """Record *node* so a later reference to it is skipped.

    *alive* holds a reference to everything measured, so no ``id()`` can
    be reused for a different object while it is a key in *visited* —
    without it a freed object's address could be recycled and a distinct
    object charged nothing.
    """
    visited.add(id(node))
    alive.append(node)


def _sizeof_or_estimate(node: Any) -> int:
    """``sys.getsizeof(node)``, or the flat estimate if it will not answer.

    ``__sizeof__`` is ordinary Python on a custom class, so it can raise
    anything a method can raise, and a custom rule may put such an object
    into a cached read. Whatever it raises arrives here *after* the wrapped
    helper returned successfully — so letting it out converts a valid read
    into a ``rule-execution-error`` and discards findings the rule already
    produced. Aborting a lint from inside cache accounting is worse than
    charging an estimate, so the estimate wins for every ordinary failure.

    ``Exception`` and not ``BaseException``: a ``KeyboardInterrupt`` or a
    ``SystemExit`` crossing this frame is someone asking the process to
    stop, and swallowing it to finish costing a cache entry would be the
    same mistake in the other direction.

    Applies to the ``str`` branch as much as the scalar one: ``str`` can be
    subclassed, and this walk is handed whatever a custom rule cached.
    """
    try:
        return sys.getsizeof(node)
    except Exception:
        return _NODE_OVERHEAD_BYTES


def _approximate_size(value: Any) -> int:
    """Roughly how many bytes *value* keeps alive, for cache accounting.

    Walks the parsed structure rather than charging a flat estimate for
    it: the readers return whole documents, and one charged as though it
    were a scalar is one the byte budget cannot see. The walk is
    iterative, descends into each container once (aliases and cycles are
    ordinary in YAML), and returns :data:`UNCACHEABLE_SIZE` if it reaches
    ``_SIZE_WALK_LIMIT`` nodes without finishing.
    """
    total = 0
    visited: Set[int] = set()
    alive: List[Any] = []
    stack: List[Any] = [value]
    walked = 0
    while stack:
        node = stack.pop()
        node_id = id(node)
        if node_id in visited:
            # A second reference to something already measured, and the
            # walk's one dedup point. It covers every node: an alias is
            # one object however many times a document names it, so both
            # the charge and the limit count objects rather than names.
            #
            # Counting references is wrong twice over: it charges a
            # 2 MiB anchored string used 64 times as 128 MiB, refusing
            # an entry that holds 2 MiB, and it lets 20,000 references
            # to one short string exhaust the limit over a graph holding
            # three objects. An abandoned walk is not free — the value
            # cannot be cached, so every rule reparses the file, which
            # costs far more than finishing.
            #
            # Registering every scalar rather than only large ones also
            # measures faster, because a repeated key is sized once
            # instead of once per occurrence.
            #
            # This is also what terminates a cycle.
            continue
        walked += 1
        if walked > _SIZE_WALK_LIMIT:
            return UNCACHEABLE_SIZE
        if isinstance(node, (str, bytes, bytearray)):
            # Not ``len``. CPython stores a string at one, two or four
            # bytes per character depending on the widest codepoint in it
            # (PEP 393), so a document of emoji retains four times the
            # length the budget would have been shown. ``getsizeof``
            # reports what the object actually holds, header included.
            size = _sizeof_or_estimate(node)
            _remember(node, visited, alive)
            total += size
            # Not an unconditional ``continue``: ruamel returns
            # ``ScalarString`` subclasses that carry an ``Anchor`` in a
            # slot, and an anchor name is authored text of any length. A
            # plain ``str`` has no slots, so this costs one memoized
            # lookup for the common case.
            _push_attributes(node, stack)
            continue
        if isinstance(node, dict):
            _remember(node, visited, alive)
            total += _NODE_OVERHEAD_BYTES * len(node)
            stack.extend(node.keys())
            stack.extend(node.values())
            _push_attributes(node, stack)
            continue
        if isinstance(node, (list, tuple, set, frozenset)):
            _remember(node, visited, alive)
            total += _NODE_OVERHEAD_BYTES * len(node)
            stack.extend(node)
            _push_attributes(node, stack)
            continue
        # A scalar is not always small: PyYAML resolves ``0x`` followed by
        # a few million hex digits into a multi-megabyte ``int``, and the
        # hex path has no digit limit to stop it. Charge what the object
        # holds, floored at the overhead a slot costs regardless.
        size = max(_sizeof_or_estimate(node), _NODE_OVERHEAD_BYTES)
        _remember(node, visited, alive)
        total += size
        _push_attributes(node, stack)
    return total or 1


def _entry_cost(value: Any, key: Any = None, sub_key: Any = None) -> int:
    """What one cache entry costs — its value, its keys, and the machinery.

    Called once, at admission. The number is then stored beside the value
    and credited back verbatim by eviction, clearing and invalidation:
    re-measuring at teardown charges back whatever the value happens to
    measure *then*, which a caller mutating a parsed document turns into
    a negative total or phantom bytes.

    *key* is the resolved path the entry is filed under. It is measured
    because it is variable — the same reason the resolution memo measures
    its own — where a flat constant is only ever right for the path length
    it was tuned against.

    *sub_key* is the rest of the call: the remaining arguments, held by
    the inner dict for as long as the entry lives. It is variable for the
    same reason and by the same authors — ``heading_line(path, heading)``
    files one entry per heading, and a heading is repository content of
    any length. Left uncharged, fifty of them at 100 KB apiece retain
    5 MB against a counter reporting 57 KB, so nothing evicts and the
    budget bounds nothing.
    """
    size = _approximate_size(value)
    if size == UNCACHEABLE_SIZE:
        return UNCACHEABLE_SIZE
    cost = size + _ENTRY_OVERHEAD_BYTES
    if isinstance(key, Path):
        cost += _path_cost(key)
    if sub_key is not None:
        sub_size = _approximate_size(sub_key)
        if sub_size == UNCACHEABLE_SIZE:
            return UNCACHEABLE_SIZE
        cost += sub_size
    return cost


class _Unsizeable:
    """Marker stored in place of a value the walk could not size.

    A value past ``_SIZE_WALK_LIMIT`` cannot be admitted — the budget
    would be recording a number that is not what the entry holds. But
    forgetting *that* costs the full abandoned walk again on every later
    call, on top of the recompute, which is strictly worse than doing no
    accounting at all. Remembering the verdict keeps the refusal and
    drops the re-walk.

    It lives in the store rather than beside it so every existing teardown
    path — eviction, ``invalidate``, ``cache_clear`` — already handles it,
    and it is charged the entry overhead it genuinely occupies.
    """

    __slots__ = ()


_UNSIZEABLE = _Unsizeable()


class BudgetedMemo:
    """A memo bounded by the bytes its entries retain, not by their count.

    Three caches in the tree hold entries whose size repository or config
    content decides rather than the code: the two pattern-literal memos in
    ``content_analysis`` (nothing caps the length of a banned pattern) and
    the markdown parse cache in ``markdown_doc`` (nothing caps the size of
    a document). A count cap on such a cache is a bound in name only —
    512 entries of a 200,000-character pattern is 102 MB, and 128 parsed
    trees of 134 KB documents is 406 MB. Refusing the large ones outright
    is worse than the leak, because the work they cache is what makes a
    document cheap on the second read, so the answer is a byte budget with
    eviction.

    Reads go straight to ``values`` and take no lock: a ``get`` racing a
    ``del`` returns the value or nothing, and nothing is just a miss. The
    dict is exposed rather than wrapped in a method because the
    pattern-keyed lookup runs once per (pattern, document) pair — 39,513
    times linting a 115-skill, 41-plugin repository — and the point of it
    is to stay a plain lookup rather than grow a call in front.

    Writes take the lock, the way ``_resolve_lock`` and ``FileCache._lock``
    do for the other process-global caches: two threads admitting the same
    key would otherwise charge one retained entry twice, and two evicting
    at once would pop a key the other already removed.

    Callers supply what the *entry* holds, since only they know that;
    :func:`_approximate_size` measures a parsed structure, and an entry it
    declines to size (:data:`UNCACHEABLE_SIZE`) is never stored. What the
    *memo* holds on top — a slot in each of the two dicts, the stored cost
    integer, and the slack a hash table carries between resizes — is added
    here rather than by every caller, so no caller can forget it and none
    has to do arithmetic on a value that might be the sentinel.
    """

    #: Charged per entry on top of the caller's figure. Two dict slots and
    #: a small int measure about 80 bytes; 256 is deliberately generous,
    #: because being over on a memory bound costs a little cache and being
    #: under makes the bound a fiction.
    ENTRY_OVERHEAD_BYTES = 256

    __slots__ = ("values", "_costs", "_bytes", "_budget", "_lock")

    def __init__(self, budget: int):
        self.values: Dict[Any, Any] = {}
        self._costs: Dict[Any, int] = {}
        self._bytes = 0
        self._budget = budget
        self._lock = threading.Lock()

    def put(self, key: Any, value: Any, cost: int) -> None:
        """Remember *value* under *key*, charged *cost* bytes."""
        if cost == UNCACHEABLE_SIZE:
            # The walk gave up, so nothing here knows what the entry
            # holds. Checked before anything is added to it: arithmetic on
            # the sentinel turns a refusal into a small positive cost.
            return
        cost += self.ENTRY_OVERHEAD_BYTES
        if cost > self._budget:
            # Remembering it would evict everything else and still not
            # fit. Recomputing costs time; retaining it costs the budget.
            return
        with self._lock:
            if key in self.values:
                # Another thread admitted it while this one was measuring.
                # Its entry is already charged, and charging again would
                # bill one retained entry twice.
                return
            while self.values and self._bytes + cost > self._budget:
                # Halves, not everything: a bound a workload can cross
                # must not be a cliff. Repeated because entries are not
                # uniform — dropping half of a memo holding one large
                # entry and many small ones need not free enough for the
                # next one.
                for stale in list(self.values)[: len(self.values) // 2 or 1]:
                    self._bytes -= self._costs.pop(stale)
                    del self.values[stale]
            self.values[key] = value
            self._costs[key] = cost
            self._bytes += cost

    def clear(self) -> None:
        with self._lock:
            self.values.clear()
            self._costs.clear()
            self._bytes = 0

    @property
    def total_bytes(self) -> int:
        return self._bytes

    @property
    def charged(self) -> Dict[Any, int]:
        """The per-entry costs, for tests asserting the accounting."""
        return self._costs


class FileCache:
    """Thread-safe cache that supports per-file invalidation.

    Internally uses a two-level dictionary::

        resolved_path -> { sub_key -> value }

    ``invalidate(file_path)`` is O(1) -- it pops the entire inner dict
    for that path.

    The cache is bounded by the memory it holds, not by a count of
    entries. A count cannot express the thing being protected: a repository
    of ten thousand small skills and one of two thousand large ones cost
    wildly different amounts at the same entry cap. Worse, a count small
    enough to be safe for the second is a cliff for the first — every rule
    sweeping the repository evicts what the previous rule cached, and the
    linter re-reads and re-parses every file for every rule. ``budget``
    is that bound, measured with :func:`_entry_cost`.
    """

    #: 128 MiB. A large marketplace (~10k documents) holds ~90 MiB of
    #: cached text and parsed documents at peak, and the budget has to sit
    #: above that: every rule sweeps the same files, so a cap the working
    #: set can cross is a cliff rather than a limit — each sweep evicts
    #: what the previous one cached and the linter re-reads and re-parses
    #: the repository once per rule.
    DEFAULT_BUDGET = 128 * 1024 * 1024

    def __init__(self, budget: int = DEFAULT_BUDGET, *, maxsize: Optional[int] = None):
        """Bound the cache by retained bytes.

        *maxsize* is the superseded entry-count bound, accepted so a
        caller written against it keeps working: ``skillsaw.utils`` is
        re-exported wholesale by ``skillsaw.rules.builtin.utils``, whose
        contract is that a custom rule importing from it keeps working
        unchanged. A count cannot be honoured here — the whole point of
        the byte budget is that entries are not the same size — so the
        value is ignored and the caller is told once.

        Note the positional form cannot be rescued: ``FileCache(2048)``
        used to mean 2,048 entries and now means 2,048 *bytes*, which is
        below the cost of a single entry. Distinguishing the two would
        take a magic threshold on the number, which is worse than the
        break it papers over. Pass ``budget=`` explicitly.
        """
        if maxsize is not None:
            warnings.warn(
                "FileCache(maxsize=...) is superseded by a byte budget and is "
                "ignored; pass budget= in bytes instead.",
                DeprecationWarning,
                stacklevel=2,
            )
        self._lock = threading.Lock()
        self._stores: List[Dict[Path, Dict[tuple, Any]]] = []
        self._budget = budget
        self._total_bytes = 0
        # Bumped by every invalidation. A reader computes outside the lock,
        # so an invalidation can land between the read and the insert — and
        # without this the pre-change value is written in *after* the drop
        # meant to remove it, and served from then on.
        self._generation = 0

    def cached(self, func: Callable) -> Callable:
        """Decorator -- equivalent to ``@lru_cache`` but with per-key eviction."""
        store: Dict[Path, Dict[tuple, Any]] = {}
        self._stores.append(store)

        def wrapper(*args, **kwargs):
            # Read before anything else this call will depend on. Resolving
            # the key is itself an answer about the filesystem, so a
            # generation captured after it cannot tell that an invalidation
            # landed in between — and a symlink retargeted in that window
            # gets the new target's bytes filed under the old target's key.
            generation = self._generation
            # And the memo's, because this cache is keyed on its answers.
            # The two are bumped by separate statements, so a read that
            # straddles either one resolved under one filesystem and would
            # be admitted under another: checking only this cache's own
            # counter passes a reader that finished between them.
            resolved_generation = resolve_generation()
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
            known_unsizeable = False
            with self._lock:
                bucket = store.get(resolved)
                if bucket is not None and sub_key in bucket:
                    cached = bucket[sub_key][1]
                    if cached is not _UNSIZEABLE:
                        return cached
                    # Sized once, found unsizeable. Recompute the value —
                    # it cannot be cached — but do not pay the walk again.
                    known_unsizeable = True
            # Compute outside the lock to avoid holding it during I/O;
            # the generation captured at entry tells the insert below
            # whether the filesystem was declared changed meanwhile.
            result = func(*args, **kwargs)
            if known_unsizeable:
                return result
            cost = _entry_cost(result, resolved, sub_key)
            if cost == UNCACHEABLE_SIZE:
                # Remember the refusal so the abandoned walk is paid once.
                marker = _entry_cost(_UNSIZEABLE, resolved, sub_key)
                if marker == UNCACHEABLE_SIZE:
                    # The sub-key is what could not be sized, and the
                    # marker is filed under it — so remembering the
                    # refusal would retain the very thing the refusal is
                    # about, charged a negative number that drives the
                    # total down instead of up. Forget it; the walk is
                    # paid again, which is the lesser cost.
                    return result
                if marker > self._budget:
                    # Same rule as a value too large to admit: eviction
                    # cannot make room, so storing it would leave the
                    # cache over the bound it exists to hold. Only a
                    # caller configuring a sub-kilobyte budget reaches
                    # this; the refusal is simply not remembered there.
                    return result
                with self._lock:
                    if (
                        self._generation == generation
                        and resolve_generation() == resolved_generation
                    ):
                        bucket = store.get(resolved)
                        if bucket is None or sub_key not in bucket:
                            if self._total_bytes + marker > self._budget:
                                self._evict(marker)
                            store.setdefault(resolved, {})[sub_key] = (marker, _UNSIZEABLE)
                            self._total_bytes += marker
                return result
            if cost > self._budget:
                # Too large for eviction to ever make room, so admitting
                # it would put the cache permanently over the bound it
                # exists to hold. Hand it back uncached; the reader
                # recomputes it next time. No marker here — this verdict
                # cost one bounded walk, not an abandoned one.
                return result
            with self._lock:
                if self._generation != generation or resolve_generation() != resolved_generation:
                    # Invalidated while this read was in flight, so the
                    # value describes the filesystem from before the
                    # change. Hand it to this caller — it is the answer
                    # they asked for — but do not let it back into the
                    # cache, where it would outlive the drop meant to
                    # remove it.
                    return result
                bucket = store.get(resolved)
                if bucket is not None and sub_key in bucket:
                    # Another caller computed this key while we were
                    # outside the lock. Its value is the one already
                    # charged, so keep it: overwriting would leave the
                    # cache holding one value and the budget recording the
                    # cost of a different one, and a later invalidation
                    # would subtract a charge that was never added.
                    #
                    # The sentinel is checked here as well as on the fast
                    # path: this is the store's other value-returning
                    # exit, and the racing caller may have found the file
                    # unsizeable while this read was in flight.
                    cached = bucket[sub_key][1]
                    return result if cached is _UNSIZEABLE else cached
                if self._total_bytes + cost > self._budget:
                    self._evict(cost)
                # Fetched after eviction, which may have dropped this
                # path's bucket along with everything else it freed.
                store.setdefault(resolved, {})[sub_key] = (cost, result)
                self._total_bytes += cost
            return result

        wrapper._store = store  # type: ignore[attr-defined]

        def _clear():
            with self._lock:
                self._generation += 1
                freed = sum(cost for bucket in store.values() for cost, _ in bucket.values())
                store.clear()
                self._total_bytes -= freed

        wrapper.cache_clear = _clear  # type: ignore[attr-defined]
        return wrapper

    def _evict(self, incoming: int = 0):
        """Free room for *incoming*, oldest first (called under lock).

        At least half the budget goes, so eviction is amortized rather
        than run on every insertion once the cache is full, and never
        less than the entry about to arrive needs — otherwise a large
        value inserted into an almost-full cache leaves it over budget.

        Stores are drained in step rather than in order. Draining the
        first one first would always empty the file-text cache, which is
        both the largest and the one worth keeping: the parsed documents
        in the other stores are derived from it and cheaper to rebuild.
        """
        target = max(self._budget // 2, incoming)
        freed = 0
        iterators = [iter(list(store)) for store in self._stores]
        exhausted = 0
        while freed < target and exhausted < len(iterators):
            exhausted = 0
            for store, paths in zip(self._stores, iterators):
                path = next(paths, None)
                if path is None:
                    exhausted += 1
                    continue
                bucket = store.pop(path, None)
                if bucket is None:
                    continue
                freed += sum(cost for cost, _ in bucket.values())
                if freed >= target:
                    break
        self._total_bytes -= freed

    def invalidate(self, file_path: Optional[Path] = None):
        """Drop cache entries.

        If *file_path* is given, only entries keyed by that resolved path
        are removed -- O(number of registered functions), safe to call from
        a worker thread without disturbing other threads' cached results.

        If *file_path* is ``None`` every entry in every registered store is
        cleared.

        **This is not the whole invalidation contract.** Entries are keyed
        by resolved path, and path resolution is memoized separately, in
        ``skillsaw.paths``. Dropping only this cache leaves that memo
        answering from the pre-change filesystem, so a link retargeted
        since then resolves to its old target and the new target's content
        is filed under it. :func:`invalidate_read_caches` is the entry
        point that clears both, in the order that makes the pair safe;
        call it, not this, whenever the filesystem may have moved.

        This method deliberately does not clear the memo itself: a
        ``FileCache`` is an ordinary object that callers construct, and one
        instance reaching out to a process-global memo would be a side
        effect no caller of a private cache could expect.
        """
        with self._lock:
            self._generation += 1
            if file_path is None:
                for store in self._stores:
                    store.clear()
                self._total_bytes = 0
            else:
                resolved = safe_resolve(file_path) or file_path
                for store in self._stores:
                    bucket = store.pop(resolved, None)
                    if bucket is not None:
                        self._total_bytes -= sum(cost for cost, _ in bucket.values())


# Singleton cache used by all utility functions.
_file_cache = FileCache()

_extra_caches: list = []


def register_cache(func):
    """Register an lru_cache-decorated function for bulk invalidation."""
    _extra_caches.append(func)
    return func


def invalidate_path_identity() -> None:
    """Declare that what a path resolves to may have changed.

    Drops the resolution memo and bumps the file cache's generation
    without emptying it. Both halves are needed and neither is the other:
    the memo holds the answers, and the cache is *keyed* by those answers,
    so a reader already in flight would otherwise finish against a
    resolution just declared stale and file its bytes under it.

    The generation is bumped rather than the cache cleared because the
    entries themselves are still good — a retargeted link does not change
    what the file it used to point at contains. Only admissions racing the
    change are refused, and a reader checks both counters precisely
    because these two statements are not one: one finishing between them
    would otherwise pass a check against whichever has not moved yet.

    This is the entry point for a caller that knows the shape of the tree
    moved but not that any file's *content* did; :func:`invalidate_read_caches`
    is the one for after a write.
    """
    clear_resolve_cache()
    with _file_cache._lock:
        _file_cache._generation += 1


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
    # Path resolution is memoized for the same reason and over the same
    # lifetime as the read caches (see ``paths._RESOLVE_CACHE``), so it is
    # dropped here too. There is no per-key eviction: a single rename can
    # change what any number of other paths resolve to.
    #
    # Resolution goes first, and the order is the whole safety of it. A
    # reader captures the cache generation before it resolves, so anything
    # that resolved from the stale memo captured a generation from before
    # the invalidation below and is refused at admission. Clearing the file
    # cache first leaves a window where a reader captures the *new*
    # generation and still resolves an old target, then files the new
    # target's bytes under it.
    invalidate_path_identity()
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


def _bounded_json_string(value: str, max_length: int = 120) -> str:
    """Render a complete, ASCII-safe JSON string within *max_length*."""
    fragments: List[str] = []
    rendered_length = 2  # Opening and closing quotes.
    for index, character in enumerate(value):
        fragment = json.dumps(character, ensure_ascii=True)[1:-1]
        suffix_length = 3 if index < len(value) - 1 else 0
        if rendered_length + len(fragment) + suffix_length > max_length:
            return f'"{"".join(fragments)}..."'
        fragments.append(fragment)
        rendered_length += len(fragment)
    return f'"{"".join(fragments)}"'


def reject_duplicate_json_keys(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    """Build a JSON object while rejecting keys a normal decoder collapses."""
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key: {_bounded_json_string(key)}")
        result[key] = value
    return result


@_file_cache.cached
def read_json_strict(file_path: Path) -> Tuple[Optional[object], Optional[str]]:
    """Like :func:`read_json`, but rejecting duplicate keys and non-finite numbers.

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
        return (
            json.loads(
                content,
                parse_constant=_reject_non_finite,
                object_pairs_hook=reject_duplicate_json_keys,
            ),
            None,
        )
    except ValueError as e:
        # Same rationale as read_json: bare ValueError, not just the
        # JSONDecodeError subclass.
        return None, str(e)
    except RecursionError:
        return None, _TOO_DEEP


def strip_jsonc(content: str) -> str:
    """Blank out JSONC comments and trailing commas, preserving every offset.

    ``.jsonc`` — and, for the hosts that accept it, a plain ``.json`` — adds
    ``//`` and ``/* */`` comments and a comma before a closing brace or
    bracket. ``json.loads`` rejects all three, so a config written the way
    its own host documents would otherwise be reported as unparseable.

    Removed characters are replaced with spaces rather than deleted, and
    newlines inside a block comment are kept. ``json.loads`` reports a parse
    error by line, column and character position, so a stripper that shifted
    the text would point the author at the wrong place in a file that really
    is broken.

    Strings are tracked, so ``{"url": "https://x"}`` keeps its ``//`` and
    ``{"a": "x,"}`` keeps its comma.
    The transform is a no-op on any valid JSON document: every branch that
    blanks a character needs a ``/`` or a ``,`` in a position plain JSON
    does not allow. :func:`read_jsonc` relies on that to keep this scan off
    the common path entirely.
    """
    out = list(content)
    length = len(content)
    index = 0
    in_string = False
    # Index of the most recent comma, and of the last character that was
    # neither whitespace nor blanked. A comma is trailing exactly when the
    # two are the same at the moment a closer arrives.
    last_comma = -1
    last_significant = -1
    while index < length:
        char = content[index]
        if in_string:
            if char == "\\":
                index += 2
                continue
            if char == '"':
                in_string = False
                last_significant = index
            index += 1
            continue
        if char == '"':
            in_string = True
            last_significant = index
            index += 1
            continue
        if char == "/" and index + 1 < length:
            following = content[index + 1]
            if following == "/":
                while index < length and content[index] != "\n":
                    out[index] = " "
                    index += 1
                continue
            if following == "*":
                end = content.find("*/", index + 2)
                # An unterminated block comment runs to end of file, which is
                # what every JSONC reader does with one.
                end = length if end == -1 else end + 2
                for position in range(index, end):
                    if out[position] != "\n":
                        out[position] = " "
                index = end
                continue
        if char in "}]":
            if last_comma != -1 and last_significant == last_comma:
                out[last_comma] = " "
            last_comma = -1
            last_significant = index
        elif char == ",":
            last_comma = index
            last_significant = index
        elif not char.isspace():
            last_significant = index
        index += 1
    return "".join(out)


@_file_cache.cached
def read_jsonc(file_path: Path) -> Tuple[Optional[object], Optional[str]]:
    """Read a JSON file that may carry comments and trailing commas.

    Always strict about duplicate keys and non-finite tokens, for the reason
    :func:`read_json_strict` gives: the locations that opt into JSONC are new
    surfaces with no shipped results a tightened parser would change.

    Parsed as-is first, and stripped only if that fails. Most files at these
    locations are plain JSON, and :func:`strip_jsonc` materializes one list
    slot per character plus a joined copy — roughly 8x the file resident,
    against 2x for an ordinary read. Parsing first keeps an unbounded,
    attacker-sized config off that path (THREAT_MODEL T11 — whole-file size
    limits are still open) and costs nothing in results, since the strip is
    a no-op on every document the first parse would have accepted. The
    reported error still comes from the stripped parse, so its line, column
    and position stay the ones this function's offset preservation exists
    for.
    """
    content = read_text(file_path)
    if content is None:
        return None, f"Failed to read {file_path.name}"
    try:
        return (
            json.loads(
                content,
                parse_constant=_reject_non_finite,
                object_pairs_hook=reject_duplicate_json_keys,
            ),
            None,
        )
    except RecursionError:
        return None, _TOO_DEEP
    except ValueError:
        pass  # May be JSONC. Fall through to the stripped parse.
    try:
        return (
            json.loads(
                strip_jsonc(content),
                parse_constant=_reject_non_finite,
                object_pairs_hook=reject_duplicate_json_keys,
            ),
            None,
        )
    except ValueError as e:
        # Same rationale as read_json: bare ValueError, not just the
        # JSONDecodeError subclass.
        return None, str(e)
    except RecursionError:
        return None, _TOO_DEEP


# PyYAML ships a libyaml-backed loader in most wheels, and it is several
# times faster than the pure-Python scanner — which matters because
# skillsaw parses YAML at least once per markdown file (frontmatter) plus
# once per config and manifest. Both loaders pair the same
# ``SafeConstructor`` and ``Resolver`` with their parser, so a document
# both accept resolves to the same value in every shape this repository
# parses. They do not accept quite the same documents, and there are
# rare tag forms both accept and resolve differently (``a: !`` is
# ``None`` on the pure loader and ``''`` on libyaml) — see
# :func:`safe_load_yaml`
# for both directions and what each means for an existing baseline.
_SAFE_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


# Structures deeper than this are rejected outright. Nothing an ecosystem
# actually ships comes close — a skill's frontmatter or a marketplace
# manifest nests a handful of levels — while a hand-crafted document can
# nest thousands, and the rules, formatters, and fixers that walk a parsed
# document all recurse. The pure-Python parser used to reject such input
# incidentally, by exhausting CPython's own stack; that was never a
# guarantee (the depth that overflows varies by platform, thread stack
# size, and Python version), so the limit is stated here instead of
# inherited from the interpreter.
_MAX_YAML_DEPTH = 100


_CONTAINER_TYPES = (dict, list, tuple, set)


def _is_container(node: Any) -> bool:
    """Whether *node* is a type :func:`_child_containers` descends into.

    Kept separate so the depth walk can ask the cheap question. Asking it
    by calling ``_child_containers`` and testing for ``None`` builds that
    node's child view first, which for a mapping means materializing its
    keys and values -- once per child, on a node whose children are almost
    all scalars.
    """
    return isinstance(node, _CONTAINER_TYPES)


def _child_containers(node: Any) -> Optional[Any]:
    """The containers *node* holds, or ``None`` when it is a scalar.

    Keys as well as values, so this walk covers what ``_approximate_size``
    covers. A mapping key can be a container: ruamel builds ruamel's own
    hashable ``CommentedKeySeq`` / ``CommentedKeyMap`` for an explicit
    ``? [a, b]`` key.

    It can be one *only at the top*, which is why counting keys changes an
    answer by at most a level. Nesting anything inside such a key needs the
    inner container to be hashable too, and ruamel builds a plain
    ``CommentedSeq`` / ``CommentedMap`` there — so ``? [[1]]`` and
    ``? [{a: 1}]`` both raise ``TypeError: unhashable type`` during load,
    and an alias chain routed through keys fails for the same reason
    before this function ever sees it. A key holds scalars or it does not
    load.

    Counted anyway: an off-by-one at the boundary is still a document the
    two walks disagree about, and the disagreement is the thing worth not
    having.
    """
    if isinstance(node, dict):
        # ``chain`` rather than two lists and a concatenation: a mapping
        # here can hold hundreds of thousands of entries, and this is
        # asked twice per node.
        return chain(node.keys(), node.values())
    if isinstance(node, (list, tuple, set)):
        return node
    return None


def _reject_overly_nested(data: Any) -> None:
    """Raise when *data* nests deeper than ``_MAX_YAML_DEPTH``.

    Iterative on purpose: a recursive depth check would be the very stack
    overflow it exists to prevent. ``RecursionError`` is the signal
    because every reader already maps it to ``_TOO_DEEP`` — the condition
    is exactly "too deep for the recursive consumers downstream".

    What a consumer recurses through is the object graph, so what is
    measured is its height. Each container's height is computed once and
    memoized, which is what makes a shared container — a YAML anchor
    referenced from several places — count at its true depth wherever it
    appears. Marking such a container visited and skipping it instead
    would measure only wherever it was reached first: a document that
    mentions a deep anchor shallowly before nesting it deeply would be
    accepted at a fraction of its real depth.

    A container reached while it is still being computed is a cycle
    (``metadata: &m {nested: *m}`` is an ordinary, valid document the
    rules already handle), and contributes nothing further rather than
    looping forever.
    """
    root_children = _child_containers(data)
    if root_children is None:
        return

    heights: Dict[int, int] = {}
    on_path: Set[int] = set()
    # Holds a reference to every node under measurement, so no id() is
    # reused for a different object while it is a key here.
    alive: List[Any] = [data]

    # One frame per level of the path currently being descended, each
    # holding its node, an *iterator* over that node's children, and the
    # height established for it so far.
    #
    # An iterator and not a materialized level. Expanding a node's children
    # onto the stack makes the stack a function of how *wide* the document
    # is rather than how deep, and filtering that expansion is whack-a-mole:
    # dropping scalars still left 300,000 frames for a mapping of 300,000
    # empty lists, because an empty list is a container. Advancing one child
    # at a time bounds the stack by path length instead, which is the thing
    # already bounded.
    #
    # ``height`` starts at 1 because a container is one level whether or not
    # it holds anything. At zero, an empty terminal collection would
    # contribute nothing while a scalar contributes one, and this measure
    # and the pre-compose event count -- which sees the empty collection's
    # start event -- would disagree by one at the boundary.
    on_path.add(id(data))
    stack: List[List[Any]] = [[data, iter(root_children), 1]]

    while stack:
        frame = stack[-1]
        node, children, _height = frame
        descended = False

        for child in children:
            if not _is_container(child):
                # A scalar contributes one level, which ``height`` already is.
                continue
            if not child:
                # An empty container's height is exactly 1, so its parent's
                # is at least 2 -- the same answer descending would reach,
                # without a frame, a memo slot or a pin for each one. Worth
                # its own branch because it is the widest remaining shape: a
                # mapping of 300,000 ``k: []`` entries is two levels deep and
                # would otherwise take a memo entry per key to establish it.
                #
                # Counted, not skipped. An empty terminal collection has a
                # start event, so the pre-compose count sees a level here;
                # dropping it instead of charging 2 makes the two halves
                # disagree at exactly the boundary, which
                # ``test_the_two_depth_bounds_agree_on_an_empty_terminal_collection``
                # exists to catch -- and did.
                if frame[2] < 2:
                    frame[2] = 2
                continue
            child_id = id(child)
            if child_id in on_path:
                # A cycle back into this subtree (``metadata: &m {nested: *m}``
                # is an ordinary document): contributes nothing further.
                continue
            known = heights.get(child_id)
            if known is not None:
                # Memoized, so a shared container -- a YAML anchor referenced
                # from several places -- counts at its true depth wherever it
                # appears rather than only where it was first reached.
                if 1 + known > frame[2]:
                    frame[2] = 1 + known
                continue
            grandchildren = _child_containers(child)
            # ``_is_container`` said yes, so this is never ``None``.
            if len(stack) >= _MAX_YAML_DEPTH:
                # The path itself is already too long. Checked on descent
                # rather than only on the way back up, so the stack stays
                # bounded by the limit instead of growing to whatever depth
                # the document spells out before anything is finalized.
                raise RecursionError(_TOO_DEEP)
            alive.append(child)
            on_path.add(child_id)
            stack.append([child, iter(grandchildren), 1])
            descended = True
            break

        if descended:
            continue

        # Children exhausted: this node's height is final.
        stack.pop()
        node_id = id(node)
        on_path.discard(node_id)
        height = frame[2]
        # Still needed alongside the path check above: an alias lets a
        # subtree measured once at a shallow position be counted again from
        # a deep one, so a graph can exceed the bound by accumulation
        # without any single descent reaching it.
        if height >= _MAX_YAML_DEPTH:
            raise RecursionError(_TOO_DEEP)
        heights[node_id] = height
        if stack and 1 + height > stack[-1][2]:
            stack[-1][2] = 1 + height


#: Event types that open and close a collection in the parse stream.
_YAML_OPEN_EVENTS = (yaml.SequenceStartEvent, yaml.MappingStartEvent)
_YAML_CLOSE_EVENTS = (yaml.SequenceEndEvent, yaml.MappingEndEvent)


def _reject_deep_before_compose(source: str, loader: Any = None) -> None:
    """Bound nesting depth before any composer sees *source*.

    This has to run first, and the reason is the whole point of the
    function. libyaml composes nodes with mutually recursive **C**
    functions carrying no recursion guard: handed a document nested past
    roughly fifty thousand levels it overruns the C stack and the process
    dies with ``SIGSEGV``. No ``except`` clause can catch that, so a
    check on the constructed object cannot be the guard — it runs
    strictly after the crash it is meant to prevent.

    libyaml's *parser* is a different animal: an explicit state machine
    keeping its stack on the heap, verified here to stream a document a
    million levels deep without trouble. So depth is counted over the
    event stream, which also lets the scan stop the moment the bound is
    crossed rather than reading the rest of a hostile file.

    A malformed document is not this function's problem — the error is
    swallowed so that ``yaml.load`` below raises the canonical one, with
    the ``problem_mark`` callers report line numbers from. That is safe
    because reaching a parse error means the parser got there without
    exceeding the bound.

    *loader* selects the parser. It matters on the retry path: the
    document arrives there precisely because libyaml stopped early on
    syntax it rejects, so a prescan using libyaml would return at that
    same point and see none of the nesting the retry is about to compose.

    **For the ruamel readers this scan is the belt and not the braces,
    and it cannot be made otherwise.** They prescan with libyaml and then
    compose with ruamel, which accepts documents libyaml does not — a
    JSON-style escaped surrogate pair, for one — so on such a file the
    scan stops at the syntax error, swallows it, and sees none of the
    nesting that follows. The obvious repair, prescanning with a parser
    that accepts everything ruamel accepts, has no implementation: the
    only parser that agrees with ruamel is ruamel, and running it here
    would parse every document twice to reach a verdict already reached.

    What holds instead is the second half. ruamel is pure Python, so past
    the interpreter's limit it *raises* where libyaml would fault, and
    every ruamel reader turns that into the same ``_TOO_DEEP`` its
    ``_reject_overly_nested`` backstop reports. Verified: a document
    carrying a surrogate-pair escape ahead of 60,000 levels of flow
    nesting — past where libyaml segfaults — comes back from
    ``read_yaml_commented`` as ``_TOO_DEEP`` with the process intact.
    The prescan is what keeps a *libyaml* composer off a hostile file;
    for ruamel it is an early exit, and losing it costs a message, not
    the bound.
    """
    depth = 0
    try:
        for event in yaml.parse(source, Loader=loader or _SAFE_LOADER):
            if isinstance(event, _YAML_OPEN_EVENTS):
                depth += 1
                # ``>=``, matching ``_reject_overly_nested``. The two
                # bounds have to agree exactly or a document falls between
                # them and one reader accepts what another rejects.
                if depth >= _MAX_YAML_DEPTH:
                    raise RecursionError(_TOO_DEEP)
            elif isinstance(event, _YAML_CLOSE_EVENTS):
                depth -= 1
    except yaml.YAMLError:
        return


def frontmatter_rewrite_is_portable(original: str, fixed: str) -> bool:
    """Whether a fix's new frontmatter is parseable by every reader.

    ``assert_portable_yaml`` guards :meth:`FrontmatteredBlock.write_frontmatter_text`,
    but that is not the path an autofix takes: a rule returns rewritten
    content and ``Linter._apply_fixes`` writes it, so a fix that rewrites
    frontmatter through ``replace_frontmatter_field`` reached disk without
    the check. Measured: a skill whose frontmatter carries a tab separator
    -- accepted by libyaml, rejected by both pure PyYAML and ruamel -- is
    unfixable on ``main`` (nothing can parse it, so no rule reports a
    fixable violation) and on this branch was renamed and written back,
    tab intact. Persisting bytes only one of our own readers accepts is
    exactly what ``assert_portable_yaml`` exists to prevent, so the guard
    belongs at the write boundary too rather than at three call sites and
    whichever the next rule adds.

    Only a *changed* frontmatter is checked. A body-only fix on a file
    whose frontmatter was already unportable is left alone: the bytes are
    not this fix's doing, ``main`` applies that fix too, and refusing it
    would be a behaviour change in the other direction.
    """
    old_fm, _ = _extract_frontmatter_text(original)
    new_fm, _ = _extract_frontmatter_text(fixed)
    if new_fm is None or new_fm == old_fm:
        return True
    try:
        safe_load_yaml(new_fm)
    except Exception:
        # Our own primary reader cannot parse it either, so there is no
        # divergence for this guard to own. Cursor's ``.mdc`` frontmatter
        # is the case that matters: ``globs: **/*.ts`` is Cursor's
        # documented syntax and an alias error to every YAML parser, so
        # its rules run on a lenient path of their own. Refusing those
        # fixes was the first thing this guard did, and it was wrong --
        # "no reader accepts this" is not the hazard; "one reader accepts
        # it and another does not" is.
        return True
    try:
        assert_portable_yaml(new_fm)
    except yaml.YAMLError:
        return False
    return True


def assert_portable_yaml(source: str) -> None:
    """Raise ``yaml.YAMLError`` if only libyaml's laxer scanner accepts *source*.

    For a **write** path, and only a write path. The readers here select
    libyaml when the wheel ships it, and its scanner accepts a little more
    than PyYAML's: ``a: |#`` is a block-scalar header with a comment to
    libyaml and a ``ScannerError`` to the pure-Python one. Reading such a
    file is not this project's problem — it already exists, and skillsaw
    reports on it. *Writing* one is: it would persist bytes that skillsaw
    itself parses on one wheel and rejects on another, which is the
    reader-agreement invariant broken by our own hand.

    Deliberately not ``roundtrip_yaml``, which would be the obvious reach.
    ruamel rejects this case, but it also rejects a duplicate mapping key
    that both PyYAML loaders accept — validating writes through it would
    newly refuse frontmatter that ``main`` writes today. The acceptance set
    to preserve is PyYAML's, so PyYAML's strict scanner is what checks it.

    A no-op when libyaml is absent: the loader that already ran *is* the
    strict one, and parsing twice would buy nothing.
    """
    if _SAFE_LOADER is yaml.SafeLoader:
        return
    yaml.load(source, Loader=yaml.SafeLoader)


def safe_load_yaml(source: Any) -> Any:
    """``yaml.safe_load``, using the libyaml parser when it is available.

    Documents nesting deeper than ``_MAX_YAML_DEPTH`` raise
    ``RecursionError``, which every caller already treats as an
    unparseable document. The bound is enforced before the document is
    composed; see :func:`_reject_deep_before_compose` for why it cannot
    be enforced afterwards.

    libyaml pairs the same ``SafeConstructor`` and ``Resolver`` with its
    own parser, so a document both loaders accept resolves to the same
    value in every shape this repository parses. There are rare tag
    forms both accept and resolve differently — ``a: !`` is ``None`` on
    the pure loader and ``''`` on libyaml. They also do not accept quite
    the same documents, and that difference runs in both directions.

    **libyaml rejects, PyYAML accepts.** The JSON-style escaped
    surrogate pair that any ASCII-safe JSON-to-YAML conversion emits for
    an astral character (an emoji in a ``description:``, say), and
    ``%YAML`` directives naming a version libyaml does not implement.
    Rather than turn files that linted cleanly into parse errors, a
    rejected document is retried on the pure-Python loader, which also
    restores that loader's message wording and ``problem_mark``. Parse
    failures are rare, so the happy path pays nothing.

    **libyaml accepts, PyYAML rejects** — and this direction cannot be
    retried, because a document libyaml accepts never reaches the retry.
    The class is *documents PyYAML's scanner rejects and libyaml
    accepts*, and it is wider than any list worth spelling out here.
    Mostly that is PyYAML being stricter than the spec; at least one
    shape is libyaml being looser.
    The shapes measured so far: a tab used as a token separator
    (``name:\tvalue``, a trailing tab, a tab before a ``#`` comment, a
    tab between a key and its ``:``); a ``?`` inside a flow collection
    (``globs: [tests/?_*.py]``); and a block-scalar header followed
    immediately by ``#``. The spec permits the first two outside
    indentation, so there libyaml is right and PyYAML is the stricter
    outlier. The third runs the other way — a comment must be preceded
    by whitespace, so ``a: |#`` is libyaml being lax where ``a: | #``
    parses on both. Either way, a file that stops reporting a parse
    error starts being linted, which can surface violations an existing
    baseline does not carry. A tab used as *indentation* stays an error
    in both.

    Note ruamel still rejects the tab class, so ``read_yaml`` and
    ``read_yaml_commented`` disagree about it. That is a real exception
    to the reader-agreement invariant, confined to this one shape.
    """
    if hasattr(source, "read"):
        # One caller hands over an open file. Everything below needs the
        # text more than once, and a stream can only be read out once.
        source = source.read()
    if _SAFE_LOADER is not yaml.SafeLoader:
        # Only libyaml needs the bound enforced *before* composition,
        # and only because its composer is recursive C with no guard.
        # PyYAML's own composer is Python: it raises where the stack
        # gives out, and ``_reject_overly_nested`` below reaches the
        # same verdict deterministically on the loaded graph. Running
        # the prescan there anyway would parse every document twice —
        # measured at 1.9x a plain load — to reach an answer the
        # backstop already gives.
        _reject_deep_before_compose(source)
    try:
        data = yaml.load(source, Loader=_SAFE_LOADER)
    except RecursionError:
        # Only reachable on the pure-Python loader, which skips the
        # prescan above: its composer recurses, so a document deeper than
        # the interpreter's limit gives out there rather than at
        # ``_MAX_YAML_DEPTH``. The verdict is the same either way — the
        # document is rejected — but the message is not, and baselines
        # fingerprint the message. Re-raised as the explicit bound so one
        # file reads the same on every wheel.
        raise RecursionError(_TOO_DEEP) from None
    except yaml.YAMLError:
        if _SAFE_LOADER is yaml.SafeLoader:
            raise
        # The retry composes with the recursive Python loader, and the
        # prescan above ran on libyaml's parser — which stopped at the
        # syntax that sent us here, before reaching anything deeper. So
        # the bound has to be re-established over this loader's own event
        # stream: without it a document libyaml rejects early and nests
        # deeply later composes unbounded, even where libyaml is
        # installed. Only the retry pays for it, which is the rare path.
        _reject_deep_before_compose(source, loader=yaml.SafeLoader)
        try:
            data = yaml.load(source, Loader=yaml.SafeLoader)
        except RecursionError:
            raise RecursionError(_TOO_DEEP) from None
    # Kept as the backstop the event count cannot be: aliases let a
    # shallow event stream build a deep object graph.
    _reject_overly_nested(data)
    return data


@_file_cache.cached
def read_yaml(file_path: Path) -> Tuple[Optional[object], Optional[str]]:
    """Cached YAML file read. Returns (data, error)."""
    content = read_text(file_path)
    if content is None:
        return None, f"Failed to read {file_path.name}"
    try:
        return safe_load_yaml(content), None
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

    Nesting is bounded here for the same reason, by the same rule, and in
    both the same places as :func:`safe_load_yaml`: the source is
    prescanned before ruamel sees it, and the loaded graph is measured
    after. ruamel is pure Python, so it raises rather than faulting — but
    it raises wherever the interpreter's own stack happens to give out,
    which is the incidental limit ``_MAX_YAML_DEPTH`` exists to replace.
    Both checks are needed for the readers to agree about a file: without
    the prescan a document a hundred levels deep is rejected by
    ``read_yaml`` and accepted here, and without the graph measurement an
    alias-built graph passes the prescan.
    """
    content = read_text(file_path)
    if content is None:
        return None, f"Failed to read {file_path.name}", None
    try:
        _reject_deep_before_compose(content)
    except RecursionError:
        return None, _TOO_DEEP, None
    ry = _RuamelYAML()
    ry.preserve_quotes = True
    try:
        data = ry.load(content)
        # The prescan bounds the depth the *source* spells out. Aliases
        # build a graph deeper than the text does: a file of one-line
        # entries, each referencing the anchor on the line before it,
        # reaches any depth at all at a syntactic depth of two. Measuring
        # the loaded graph as well is what ``safe_load_yaml`` already does
        # after its own prescan. Every reader needs both halves, and needs
        # them to agree: two rules reading the same file through different
        # readers must reach the same verdict on it.
        _reject_overly_nested(data)
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


def roundtrip_yaml(source: str) -> Tuple[Any, Any]:
    """Round-trip-load *source* under the readers' nesting bound.

    Returns ``(yaml, data)`` — the loader to dump back through, so a
    caller keeps the round-trip style it read with — and raises
    ``RecursionError`` on a document past ``_MAX_YAML_DEPTH``, like
    every other reader here.

    Every YAML write path must come through here. :func:`read_yaml_commented`
    is not an option for one: that reader is cached, and mutating what it
    returns corrupts the document every later reader is handed — so a
    caller intending to edit and write back has to load its own copy. A
    bare ``ruamel.yaml.YAML()`` is the wrong way to get one, because it
    carries neither half of the nesting bound, and a write path reads the
    file again rather than the tree's cached copy, so it is its own way in
    for untrusted content.
    """
    _reject_deep_before_compose(source)
    yaml_rt = _RuamelYAML()
    yaml_rt.preserve_quotes = True
    data = yaml_rt.load(source)
    _reject_overly_nested(data)
    return yaml_rt, data


@_file_cache.cached
def read_frontmatter_commented(
    file_path: Path,
) -> Tuple[Any, Optional[str], Optional[int]]:
    """Read Markdown frontmatter as line-preserving YAML.

    Returns the same ``(data, error, error_line)`` contract as
    :func:`read_yaml_commented`, but parses only the YAML between the opening
    and closing ``---`` delimiters. Reported parse-error lines are translated
    to file-absolute lines; successful ruamel nodes retain frontmatter-relative
    positions, so callers add the opening-delimiter offset when using
    :func:`commented_key_line` or :func:`commented_item_line`.
    """
    content = read_text(file_path)
    if content is None:
        return None, f"Failed to read {file_path.name}", None
    frontmatter, offset = _extract_frontmatter_text(content)
    if frontmatter is None:
        return None, None, None
    try:
        # Both halves of the bound, like every other reader: the event
        # count before anything composes, and the graph measurement after,
        # because aliases build depth the source never spells out.
        _reject_deep_before_compose(frontmatter)
        ry = _RuamelYAML()
        ry.preserve_quotes = True
        data = ry.load(frontmatter)
        _reject_overly_nested(data)
        return data, None, None
    except _RuamelYAMLError as error:
        line = None
        if hasattr(error, "problem_mark") and error.problem_mark is not None:
            line = error.problem_mark.line + 1 + offset
        return None, str(error), line
    except ValueError as error:
        return None, str(error), None
    except RecursionError:
        return None, _TOO_DEEP, None


def commented_key_line(node: Any, key: Any) -> Optional[int]:
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
    try:
        # The composer this calls is the same recursive C code every
        # other reader is guarded against: handed a deeply nested
        # document it overruns the C stack and the process dies with
        # SIGSEGV, which no ``except`` can catch. Every caller today
        # runs after the block's frontmatter parsed through a bounded
        # reader, so nothing this deep should reach here — but "should"
        # is what the guard is for, and a reader without it is what the
        # next person will copy.
        _reject_deep_before_compose(text)
        node = yaml.compose(text, Loader=_SAFE_LOADER)
    except yaml.YAMLError:
        return None
    except RecursionError:
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
    lines = {}
    for key in data:
        # A merge-resolved key is visible while iterating the map but has no
        # position at this level. Keep the field in the parsed tree and omit
        # only its line; the anchor's nested nodes still retain their own
        # source positions for rules that inspect the value.
        line = commented_key_line(data, key)
        if line is not None:
            lines[key] = line + offset
    return lines


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


def frontmatter_error_message(content: str) -> str:
    """Why *content*'s frontmatter did not parse, as a reportable message.

    ``parse_frontmatter`` folds every failure into the same ``(None, ...)``
    return, so its callers cannot tell a syntax error from this project's
    own nesting bound. That produced a message which was simply false: a
    document nested past ``_MAX_YAML_DEPTH`` -- or one whose depth is built
    by aliases, two levels as text -- is well-formed YAML that ``main``
    parses and lints, and reporting it as "malformed YAML or missing
    closing ---" tells an author to go looking for a typo that is not
    there.

    The re-parse costs one extra load and runs only on the error path,
    where a violation is being built anyway. Both halves of the bound are
    covered because ``safe_load_yaml`` carries both, and only the depth
    verdict is distinguished -- anything else keeps the generic wording,
    which for an actual syntax error is accurate.
    """
    text, _ = _extract_frontmatter_text(content)
    if text is not None:
        try:
            safe_load_yaml(text)
        except RecursionError:
            return (
                f"Frontmatter nesting exceeds the {_MAX_YAML_DEPTH}-level reader "
                "bound, so it was not parsed (the document may be valid YAML)"
            )
        except Exception:
            pass
    return "Invalid frontmatter (malformed YAML or missing closing ---)"


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
        data = safe_load_yaml(m.group(1))
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

    Carries the same depth bound as every other reader. ruamel is pure
    Python, so a deep document raises rather than faulting — but it
    raises wherever the interpreter's stack happens to give out, which
    is the incidental limit ``_MAX_YAML_DEPTH`` exists to replace, and
    an escaping ``RecursionError`` becomes an unbaselinable
    rule-execution error rather than a parse failure the caller handles.
    """
    try:
        _reject_deep_before_compose(text)
    except RecursionError:
        return None
    ry = _RuamelYAML()
    ry.preserve_quotes = True
    try:
        data = ry.load(text)
        _reject_overly_nested(data)
        return data
    except (_RuamelYAMLError, ValueError, RecursionError):
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
