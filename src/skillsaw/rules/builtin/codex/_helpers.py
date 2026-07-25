"""Shared helpers for the OpenAI Codex plugin rules.

Spec: https://developers.openai.com/plugins/build/plugins
"""

import re
from typing import Optional

from skillsaw.context import RepositoryType
from skillsaw.rules.builtin.marketplace.json_valid import (
    has_parent_traversal,
    is_absolute_path,
)

CODEX_PLUGIN_REPO_TYPES = {RepositoryType.CODEX_PLUGIN}
CODEX_MARKETPLACE_REPO_TYPES = {RepositoryType.CODEX_MARKETPLACE}

# "Use a stable plugin `name` in kebab-case. Plugin hosts use it as the
# plugin identifier and component namespace."
KEBAB_CASE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def path_problem(value: str, root_label: str) -> Optional[str]:
    """Why *value* is not a usable manifest path, or ``None`` if it is.

    The Codex docs state manifest paths must "resolve relative to the
    plugin root, and stay inside the plugin root" (and, for marketplace
    sources, the marketplace root). Absolute paths and ``..`` traversal
    both break that guarantee; the missing ``./`` prefix is only a style
    nudge, so it is reported separately by callers.
    """
    if is_absolute_path(value):
        return f"absolute path '{value}' — paths must be relative to the {root_label}"
    if has_parent_traversal(value):
        return f"path '{value}' contains '..' — paths must stay inside the {root_label}"
    return None
