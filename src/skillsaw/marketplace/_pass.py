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

from skillsaw.paths import clear_resolve_cache


def _start_resolution_pass() -> None:
    """Drop resolutions carried over from an earlier operation."""
    clear_resolve_cache()
