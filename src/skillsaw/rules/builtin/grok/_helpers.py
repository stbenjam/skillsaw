"""Shared helpers for the Grok Build plugin and marketplace rules.

The vocabulary — marker names, resolution orders, the name and ``sha``
patterns, the component table — lives in ``skillsaw.formats.grok``. What is
here is the small amount of rule-side machinery three of those rules share:
which repository types each activates in, why a declared path is unusable,
and how a consolidated finding names examples without growing without bound.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional

from skillsaw.context import RepositoryType
from skillsaw.diagnostics import safe_display
from skillsaw.paths import escapes_root, has_parent_traversal, is_absolute_path

# Semantic Versioning 2.0.0, defined once beside the rule that needed it
# first rather than restated here — the same reasoning ``formats.grok`` uses
# for borrowing ``inline_documents`` from ``formats.codex``.
from ..mcp_registry._helpers import SEMVER

# A Grok marketplace repository contains the plugins it catalogs, so the
# plugin rules have to fire there too — the same reason the Codex sets carry
# MARKETPLACE alongside the plugin type. Without it, ``--type
# grok-marketplace`` would discover every local plugin and check none of
# their manifests.
GROK_PLUGIN_REPO_TYPES = frozenset({RepositoryType.GROK_PLUGIN, RepositoryType.GROK_MARKETPLACE})
GROK_MARKETPLACE_REPO_TYPES = frozenset({RepositoryType.GROK_MARKETPLACE})

#: Names a consolidated finding shows before it says "and N more". A drifted
#: index or a directory of dead declarations is one decision for the author;
#: naming every one of them buries the rest of the run.
SAMPLE_LIMIT = 3


def escape_reason(value: str, root: Path) -> Optional[str]:
    """How *value* leaves *root*, or ``None`` when it stays inside.

    Grok resolves a declared path against the plugin root and a catalog
    source against the marketplace root, and drops anything that escapes —
    verified against a target that exists and holds real content, so
    containment is enforced rather than incidental. Symlinks are why the
    lexical checks are not enough: ``./skills-link`` has no ``..`` and is
    not absolute, and still lands outside.

    The caller names the root and what the escape costs, so one phrase
    serves both a plugin's manifest and a marketplace's catalog.
    """
    if is_absolute_path(value):
        return "is absolute"
    if has_parent_traversal(value):
        return "contains '..'"
    if escapes_root(value, root):
        return "resolves through a symlink"
    return None


def sample(names: Iterable[str], limit: int = SAMPLE_LIMIT) -> str:
    """*names* rendered for a message, bounded to *limit* with a count."""
    ordered: List[str] = [safe_display(name) for name in names]
    shown = ", ".join(ordered[:limit])
    remaining = len(ordered) - limit
    if remaining > 0:
        shown += f", and {remaining} more"
    return shown


def is_semver(value: str) -> bool:
    """Whether *value* is a Semantic Versioning 2.0.0 string."""
    return SEMVER.match(value) is not None
