"""State-free filesystem discovery of repositories and ecosystem content.

The ``claude`` and ``codex`` modules handle ecosystem-specific content,
while ``detect`` and ``excludes`` provide repository-wide helpers. This
module contains shared composition helpers. Discovery modules must never
import from ``skillsaw.context`` — the context imports them.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Iterable, List

from skillsaw.paths import safe_exists, safe_resolve

# Repository-relative directories that host Agent Skills by convention.
# The ``SKILL.md`` spec is portable, so every path added here earns the
# full skill rule set for another tool at no rule-authoring cost:
# ``.agents/skills`` is the vendor-neutral location every tool below also
# honours, and the rest are each tool's own default.
CONVENTIONAL_SKILL_DIRS = (
    ".agents/skills",  # portable — Cursor, Cline, Copilot, Codex, Claude Code
    ".apm/skills",
    ".claude/skills",
    ".github/skills",  # Copilot
    ".cursor/skills",  # Cursor
    ".clinerules/skills",  # Cline — first in its own resolution order
    ".cline/skills",  # Cline
    ".qwen/skills",  # Qwen Code
)


def exact_name_exists(parent: Path, name: str) -> bool:
    """Return whether *parent* contains a file entry with exactly *name*.

    ``Path.exists()`` follows the host filesystem's case rules. On macOS a
    lowercase ``skill.md`` therefore satisfies a probe for ``SKILL.md``, even
    though ecosystem filenames are case-sensitive. Reading directory entries
    preserves the authored spelling on both case-sensitive and insensitive
    filesystems.
    """
    # O(1) reject before listing the directory: most candidates have no
    # entry under this name at all, callers feed plain files as *parent*,
    # and a dangling symlink has an entry but no target. This keeps the
    # repo-wide discovery walks at one stat per miss, as before the
    # case-sensitive probe.
    if not safe_exists(parent / name):
        return False
    try:
        with os.scandir(parent) as entries:
            # ``is_file()`` follows symlinks, so a link to a real file
            # matches while a directory squatting on the name does not.
            return any(entry.name == name and entry.is_file() for entry in entries)
    except (OSError, ValueError):
        return False


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
