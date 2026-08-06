"""State-free filesystem discovery of repositories and ecosystem content.

The ``claude`` and ``codex`` modules handle ecosystem-specific content,
while ``detect`` and ``excludes`` provide repository-wide helpers. This
module contains shared composition helpers. Discovery modules must never
import from ``skillsaw.context`` — the context imports them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List

from skillsaw.paths import safe_resolve


def merge_plugin_dirs(*plugin_groups: Iterable[Path]) -> List[Path]:
    """Plugin directories from every ecosystem, deduplicated by resolved path.

    Shared by the CLI's merged multi-path context and
    :meth:`RepositoryContext.distinct_plugin_dirs`.
    """
    seen: Dict[Path, Path] = {}
    for group in plugin_groups:
        for path in group:
            key = safe_resolve(path) or path
            if key not in seen:
                seen[key] = path
    return list(seen.values())
