"""Where one public marketplace operation begins.

``safe_resolve`` memoizes for the lifetime of a *pass*, which inside the
linter is bounded by ``RepositoryContext`` construction and torn down by
``invalidate_read_caches()``. The public marketplace helpers have no such
bracket: a library caller invokes ``init_marketplace`` or an ``add_*``
helper directly, and the memo it fills outlives the call.

That is only a speed optimization over a filesystem nobody changed —
until somebody does. A symlink retargeted between two operations makes the
second one answer with the first one's target, so a caller can inspect or
write the repository it just moved away from. Each entry point therefore
starts its own pass.
"""

from __future__ import annotations

from skillsaw.utils import invalidate_path_identity


def _start_resolution_pass() -> None:
    """Drop resolutions carried over from an earlier operation.

    Through :func:`invalidate_path_identity`, which advances the resolution
    memo *and* the file cache's generation, and never ``clear_resolve_cache``
    alone, which advances only the first. ``FileCache`` is keyed by resolved
    paths, so a reader that resolved before the drop and admits after it
    files the new target's bytes under the old target's key; moving both
    counters is what refuses that admission. A symlink retargeted between
    two operations -- the case the module docstring above describes -- is
    exactly the "shape of the tree moved, but no file's content" that helper
    documents itself as the entry point for.
    """
    invalidate_path_identity()
