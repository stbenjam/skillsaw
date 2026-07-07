"""
Per-rule documentation helpers shared by the `explain` command, the
output formatters, and the documentation site generator.

Every builtin rule has a stable documentation URL at
``https://skillsaw.org/rules/<rule-id>/``.  Long-form documentation
(rationale, bad/good examples) lives in markdown files shipped as
package data under ``skillsaw/rules/docs/<rule-id>.md`` so that
``skillsaw explain`` works offline.
"""

from pathlib import Path
from typing import List, Optional, Tuple

DOCS_BASE_URL = "https://skillsaw.org/rules/"

_RULE_DOCS_DIR = Path(__file__).parent / "rules" / "docs"


def rule_doc_url(rule_id: str) -> str:
    """Stable documentation URL for a builtin rule."""
    return f"{DOCS_BASE_URL}{rule_id}/"


def load_rule_docs(rule_id: str) -> Optional[str]:
    """Load long-form markdown documentation for a rule, if it exists.

    Returns the markdown text, or None when the rule has no long-form
    docs yet (pages and `explain` output render gracefully without it).
    """
    doc_path = _RULE_DOCS_DIR / f"{rule_id}.md"
    if not doc_path.is_file():
        return None
    return doc_path.read_text(encoding="utf-8").strip()


def find_rule_class(rule_id: str) -> Tuple[Optional[type], Optional[str], List[str]]:
    """Locate a rule class by id across builtin rules and installed plugins.

    Shared by ``skillsaw explain`` and the MCP server's ``explain_rule``
    tool. Returns ``(rule_class, plugin_name, known_ids)``: *rule_class* is
    ``None`` when the id is unknown, *plugin_name* is ``None`` for builtin
    rules, and *known_ids* lists every rule id seen (for suggestions).
    """
    # Late imports: rules.builtin walks every rule module and plugins hit
    # entry points — neither belongs at import time of this small helper.
    from .rules.builtin import BUILTIN_RULES

    known_ids: List[str] = []
    for candidate in BUILTIN_RULES:
        rule = candidate()
        known_ids.append(rule.rule_id)
        if rule.rule_id == rule_id:
            return candidate, None, known_ids

    from .plugins import load_plugins

    for plugin in load_plugins():
        for candidate in plugin.rule_classes:
            try:
                rule = candidate()
            except Exception:
                continue
            known_ids.append(rule.rule_id)
            if rule.rule_id == rule_id:
                return candidate, plugin.name, known_ids

    return None, None, known_ids
