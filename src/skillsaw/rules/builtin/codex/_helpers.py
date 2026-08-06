"""Shared helpers for the OpenAI Codex plugin rules.

Spec: https://developers.openai.com/plugins/build/plugins
"""

import json
import re
from pathlib import Path
from typing import Optional

from skillsaw.context import RepositoryType
from skillsaw.diagnostics import safe_display
from skillsaw.paths import escapes_root, has_parent_traversal, is_absolute_path
from skillsaw.rules.builtin.utils import (  # noqa: F401  — re-exported for rule modules
    read_text,
    reject_nonfinite_json_number,
)

# A Codex marketplace repository contains the plugins it catalogs, so the
# plugin rules have to fire there too — the same reason PLUGIN_REPO_TYPES
# carries MARKETPLACE alongside SINGLE_PLUGIN. Without it, an explicit
# ``--type codex-marketplace`` run discovers every local plugin and then
# checks none of their manifests.
CODEX_PLUGIN_REPO_TYPES = {RepositoryType.CODEX_PLUGIN, RepositoryType.CODEX_MARKETPLACE}
CODEX_MARKETPLACE_REPO_TYPES = {RepositoryType.CODEX_MARKETPLACE}

# "Use a stable plugin `name` in kebab-case. Plugin hosts use it as the
# plugin identifier and component namespace."
# ``\Z``, not ``$``: ``$`` also matches immediately before a trailing
# newline, so ``"my-plugin\n"`` would pass as kebab-case and the
# registration autofix would write it into the published catalog.
KEBAB_CASE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*\Z")


def nonfinite_constant_error(file_path: Path) -> str:
    """The strict-JSON defect the lenient shared reader accepted, or ``""``.

    ``read_json()`` inherits Python's ``NaN``/``Infinity``/``-Infinity``
    extensions, but Codex's strict parser rejects them — and so does the
    registration fixer, so without this a document could pass validity yet
    refuse every fix. The substring test only gates the reparse; a quoted
    ``"NaN"`` inside a string value still parses cleanly here.
    """
    content = read_text(file_path)
    if content is None or ("NaN" not in content and "Infinity" not in content):
        return ""
    try:
        json.loads(content, parse_constant=reject_nonfinite_json_number)
    except ValueError as e:
        return str(e)
    return ""


def path_problem(value: str, root_label: str, root: Optional[Path] = None) -> Optional[str]:
    """Why *value* is not a usable manifest path, or ``None`` if it is.

    The Codex docs state manifest paths must "resolve relative to the
    plugin root, and stay inside the plugin root" (and, for marketplace
    sources, the marketplace root). Absolute paths and ``..`` traversal
    both break that guarantee; the missing ``./`` prefix is only a style
    nudge, so it is reported separately by callers.

    Lexical checks alone are not enough. ``./skills-link`` has no ``..``
    and is not absolute, yet it leaves the root entirely when
    ``skills-link`` is a symlink pointing outside it — and for a
    marketplace source that means discovering and "registering" a plugin
    that is not in the repository. When *root* is supplied the candidate
    is resolved against it and rejected unless it stays beneath it.
    """
    if is_absolute_path(value):
        return f"absolute path '{safe_display(value)}' — paths must be relative to the {root_label}"
    if has_parent_traversal(value):
        return (
            f"path '{safe_display(value)}' contains '..' — paths must stay inside the {root_label}"
        )
    if root is not None and escapes_root(value, root):
        return (
            f"path '{safe_display(value)}' resolves outside the {root_label} — check for a symlink"
        )
    return None
