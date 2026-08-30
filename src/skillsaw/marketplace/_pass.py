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

    Through :func:`invalidate_path_identity`, not ``clear_resolve_cache``
    alone. The memo holds the answers and ``FileCache`` is *keyed* by
    those answers, so dropping one without telling the other leaves a
    reader that resolved from the stale memo free to finish and file the
    new target's bytes under the old resolved path. Clearing the memo
    directly is exactly the shape that had to be closed at two other call
    sites before this one existed, and the docstring above -- a symlink
    retargeted between two operations -- is precisely the "shape of the
    tree moved" that helper is the entry point for.
    """
    invalidate_path_identity()
