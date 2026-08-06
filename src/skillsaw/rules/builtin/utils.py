"""Shared YAML/JSON/text helpers for the rule layer.

Most of the implementation moved to the core :mod:`skillsaw.utils` module so
that core modules (``blocks``, ``context``, ``lint_tree``) can use it without
importing this rule package (which would invert the layering and create an
import cycle).  Rule modules, custom rules, and tests that still do
``from skillsaw.rules.builtin.utils import ...`` keep working unchanged via
the re-exports below.

Helpers that only the rules need — the strict-JSON reader below, which
several ecosystems (Codex, Agent Plugins) each require in exactly the same
form — live here rather than in core, so no ecosystem package has to import
another ecosystem's private helpers to reuse them.
"""

import json
from pathlib import Path
from typing import Any, Optional, Tuple

from skillsaw.utils import *  # noqa: F401,F403
from skillsaw.utils import (  # noqa: F401  — underscore names ``*`` does not re-export
    _FRONTMATTER_RE,
    _extract_frontmatter_text,
    _fast_top_level_key_lines,
)
from skillsaw.utils import read_text


def reject_nonfinite_json_number(value: str) -> None:
    """Reject JavaScript number extensions that strict JSON does not allow.

    ``json.loads`` accepts ``NaN``/``Infinity``/``-Infinity`` by default; the
    strict parsers the specs describe do not.  Passed as ``parse_constant`` so
    validity rules and fixers reject exactly the same documents.
    """
    raise ValueError(f"non-finite JSON number: {value}")


def strict_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    """Parse a UTF-8 document as strict JSON without network access."""
    content = read_text(path)
    if content is None:
        return None, "could not read file"
    try:
        return json.loads(content, parse_constant=reject_nonfinite_json_number), None
    except json.JSONDecodeError as error:
        return None, f"{error.msg} at line {error.lineno}, column {error.colno}"
    except ValueError as error:
        return None, str(error)
    except RecursionError:
        return None, "JSON nesting is too deep"
