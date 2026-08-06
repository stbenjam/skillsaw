"""State-free path exclusion matching shared by discovery consumers."""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import Callable, List, Tuple

from skillsaw.paths import safe_resolve


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
    try:
        resolved = safe_resolve(path)
        if resolved is None:
            return False
        rel = str(resolved.relative_to(root))
    except ValueError:
        return False
    return any(
        fnmatch.fnmatch(rel, variant) for pattern in patterns for variant in variants_for(pattern)
    )
