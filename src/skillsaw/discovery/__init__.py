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
    ".opencode/skills",  # OpenCode 2.0
    ".opencode/skill",  # OpenCode 1.x — still loaded by 2.0
    ".devin/skills",  # Devin CLI / Desktop, preferred spelling
    ".windsurf/skills",  # Windsurf Cascade (portable Agent Skills dialect)
)

# Committed project memory: notes a team checks in for whatever agent reads
# the checkout, the shared counterpart of Claude Code's per-developer auto
# memory. The convention predates any one tool — projects were committing
# ``.agents/memory/`` before Muse Code shipped — and Muse Code reads it, the
# way it and everything else read ``AGENTS.md``. Owned by no ecosystem, so
# it lives here rather than in a ``formats/`` module.
AGENT_MEMORY_DIR = (".agents", "memory")

# The index of that directory: one line per topic file. A reader loads it
# whole (Muse Code injects it at session start, even in an untrusted
# workspace) and follows the paths it lists on demand.
AGENT_MEMORY_INDEX = "MEMORY.md"


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
