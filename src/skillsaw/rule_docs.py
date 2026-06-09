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
from typing import Optional

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
