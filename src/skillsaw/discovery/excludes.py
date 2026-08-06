"""State-free path exclusion matching shared by discovery consumers."""

from __future__ import annotations

import fnmatch
import functools
from pathlib import Path
from typing import List, Tuple

from skillsaw.paths import safe_resolve


@functools.lru_cache(maxsize=None)
def pattern_variants(pattern: str) -> Tuple[str, ...]:
    """Expand a pattern with gitignore's zero-directory ``**/`` meaning."""
    variants = {pattern}
    if pattern.startswith("**/"):
        variants.add(pattern[3:])
    return tuple(sorted(variants))


def path_matches_patterns(path: Path, root: Path, patterns: List[str]) -> bool:
    """Return whether *path*, relative to resolved *root*, matches a pattern."""
    if not patterns:
        return False
    try:
        resolved = safe_resolve(path)
        if resolved is None:
            return False
        rel = str(resolved.relative_to(root))
    except ValueError:
        return False
    return any(
        fnmatch.fnmatch(rel, variant)
        for pattern in patterns
        for variant in pattern_variants(pattern)
    )
