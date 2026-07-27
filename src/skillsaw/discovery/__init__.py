"""Filesystem discovery of ecosystem plugin content.

One state-free module per ecosystem (``discovery/codex.py``); this
package holds only the ecosystem-neutral helpers. These modules must
never import from ``skillsaw.context`` — the context imports them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from skillsaw.paths import safe_resolve


def merge_plugin_dirs(plugins: List[Path], codex_plugins: List[Path]) -> List[Path]:
    """Claude and Codex plugin directories, deduplicated by resolved path.

    Shared by the CLI's merged multi-path context and
    :meth:`RepositoryContext.distinct_plugin_dirs`.
    """
    seen: Dict[Path, Path] = {}
    for p in (*plugins, *codex_plugins):
        key = safe_resolve(p) or p
        if key not in seen:
            seen[key] = p
    return list(seen.values())
