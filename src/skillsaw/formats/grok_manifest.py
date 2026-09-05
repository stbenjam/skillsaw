"""Grok Build 1.0.13's typed plugin-manifest JSON contract.

Pinned upstream PluginManifest/Author/PathOrPaths definitions distinguish
struct-member duplicates from ignored metadata and inline serde_json::Value.
This validator keeps invalid authored content available to the diagnostic tree;
it does not change discovery or the shared JSON readers of other ecosystems.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from skillsaw.diagnostics import safe_display
from skillsaw.utils import has_utf8_bom, read_text

OPTIONAL_STRINGS = frozenset({"version", "description", "homepage", "repository", "license"})
DIRECTORY_FIELDS = frozenset({"skills", "commands", "agents"})
INLINE_FIELDS = frozenset({"hooks", "mcpServers", "lspServers"})
AUTHOR_FIELDS = frozenset({"name", "email", "url"})
MANIFEST_FIELDS = (
    OPTIONAL_STRINGS | DIRECTORY_FIELDS | INLINE_FIELDS | {"name", "author", "keywords"}
)


class _Object(dict):
    """Last-value object with duplicate names retained for typed fields."""

    def __init__(self, pairs):
        super().__init__()
        self.duplicates = set()
        for key, value in pairs:
            if key in self:
                self.duplicates.add(key)
            self[key] = value


def _nonfinite(token: str) -> None:
    raise ValueError(f"non-finite JSON number: {token}")


def read_manifest_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    """Read manifest JSON without silently normalizing BOMs or duplicates."""
    if has_utf8_bom(path):
        return None, "UTF-8 BOM is not accepted by Grok's manifest loader"
    content = read_text(path)
    if content is None:
        return None, "could not read file"
    try:
        return json.loads(content, object_pairs_hook=_Object, parse_constant=_nonfinite), None
    except json.JSONDecodeError as exc:
        return None, f"{exc.msg} at line {exc.lineno}, column {exc.colno}"
    except ValueError as exc:
        return None, str(exc)
    except RecursionError:
        return None, "JSON nesting is too deep"


def _duplicates(value: Dict[str, Any], fields: frozenset[str], prefix: str = "") -> List[str]:
    if not isinstance(value, _Object):
        return []
    return [
        f"Duplicate manifest field '{prefix}{safe_display(key)}'"
        for key in sorted(value.duplicates & fields)
    ]


def manifest_type_errors(data: Dict[str, Any]) -> List[str]:
    """Return typed-member errors; plugin-name syntax remains the rule's check.

    Optional strings/path unions accept null. The defaulted keywords vector
    accepts omission but not null. PathOrInline accepts any JSON value, so
    it is deliberately not subject to directory-path array checks.
    """
    errors = _duplicates(data, MANIFEST_FIELDS)
    for key in sorted(OPTIONAL_STRINGS):
        value = data.get(key)
        if value is not None and not isinstance(value, str):
            errors.append(f"'{key}' must be a string or null")
    for key in sorted(DIRECTORY_FIELDS):
        value = data.get(key)
        if value is not None and not (
            isinstance(value, str)
            or isinstance(value, list)
            and all(isinstance(item, str) for item in value)
        ):
            errors.append(f"'{key}' must be a path string, an array of path strings, or null")
    if "keywords" in data:
        value = data["keywords"]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            errors.append("'keywords' must be an array of strings")
    author = data.get("author")
    if author is not None:
        if not isinstance(author, dict):
            errors.append("'author' must be an object or null")
        else:
            errors.extend(_duplicates(author, AUTHOR_FIELDS, "author."))
            for key in sorted(AUTHOR_FIELDS):
                value = author.get(key)
                if value is not None and not isinstance(value, str):
                    errors.append(f"'author.{key}' must be a string or null")
    return errors
