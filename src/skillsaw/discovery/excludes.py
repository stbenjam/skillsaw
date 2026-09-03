"""State-free path exclusion matching shared by discovery consumers."""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from skillsaw.paths import relative_to_str, safe_resolve


def pattern_variants(pattern: str) -> Tuple[str, ...]:
    """Expand a pattern with gitignore's zero-directory ``**/`` meaning."""
    variants = {pattern}
    if pattern.startswith("**/"):
        variants.add(pattern[3:])
    return tuple(sorted(variants))


def path_matches_patterns(
    path: Path,
    root: Path,
    patterns: List[str],
    variants_for: Callable[[str], Tuple[str, ...]] = pattern_variants,
) -> bool:
    """Match *path* using a pure or caller-owned pattern expander."""
    if not patterns:
        return False
    resolved = safe_resolve(path)
    if resolved is None:
        return False
    rel = relative_to_str(resolved, root)
    if rel is None:
        return False
    return any(
        fnmatch.fnmatch(rel, variant) for pattern in patterns for variant in variants_for(pattern)
    )


def is_root_or_ancestor_excluded(
    path: Path,
    boundary: Optional[Path],
    is_excluded: Callable[[Path], bool],
) -> bool:
    """Whether *path* or any ancestor within *boundary* is excluded."""
    current = path
    resolved_boundary = safe_resolve(boundary) if boundary is not None else None
    while True:
        if is_excluded(current):
            return True
        if boundary is not None and current == boundary:
            break
        if resolved_boundary is not None and current == resolved_boundary:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    return False
