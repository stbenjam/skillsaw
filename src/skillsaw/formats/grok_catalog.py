"""Grok Build 1.0.13 marketplace catalog decoding.

MarketplaceIndex and its entry/owner/author structs reject recognized
duplicates. The custom IndexSource visitor accepts duplicates but decodes
every value before keeping the last. This boundary is distinct from the
display index and from installation policy.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from skillsaw.utils import has_utf8_bom, read_text

CATALOG_FIELDS = frozenset({"name", "description", "owner", "plugins"})
ENTRY_STRINGS = frozenset({"version", "description", "category", "homepage"})
ENTRY_LISTS = frozenset({"tags", "keywords", "domains"})
ENTRY_FIELDS = ENTRY_STRINGS | ENTRY_LISTS | {"name", "author", "source"}
SOURCE_FIELDS = frozenset({"type", "source", "url", "path", "ref", "sha"})


class _Object(dict):
    """Retain source member occurrences, including overwritten values."""

    def __init__(self, pairs):
        super().__init__(pairs)
        self.pairs = pairs
        seen = set()
        self.duplicates = set()
        for key, _value in pairs:
            if key in seen:
                self.duplicates.add(key)
            seen.add(key)


def _nonfinite(token: str) -> None:
    raise ValueError(f"non-finite JSON number: {token}")


def read_catalog_json(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    """Read the catalog without normalizing its BOM or duplicate members."""
    if has_utf8_bom(path):
        return None, "UTF-8 BOM is not accepted by Grok's catalog loader"
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


def _duplicates(data: Dict[str, Any], fields: frozenset[str], prefix: str = "") -> List[str]:
    return [
        f"Duplicate catalog field '{prefix}{key}'"
        for key in sorted(getattr(data, "duplicates", set()) & fields)
    ]


def _name(data: Dict[str, Any], prefix: str) -> List[str]:
    if "name" not in data:
        return [f"{prefix}missing required 'name'"]
    if not isinstance(data["name"], str):
        return [f"{prefix}'name' must be a string"]
    # Empty names are accepted by the typed decoder. Local display names
    # come from the effective plugin manifest, not this catalog string.
    return []


def _strings(data: Dict[str, Any], fields: frozenset[str], prefix: str) -> List[str]:
    return [
        f"{prefix}{key} must be a string or null"
        for key in sorted(fields)
        if data.get(key) is not None and not isinstance(data[key], str)
    ]


def _person(value: Any, prefix: str, *, owner: bool = False) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, dict):
        return [f"{prefix} must be an object or null"]
    fields = frozenset({"name", "email"} if owner else {"name"})
    errors = _duplicates(value, fields, prefix + ".")
    errors.extend(_name(value, prefix + " "))
    if owner:
        errors.extend(_strings(value, frozenset({"email"}), prefix + "."))
    return errors


def _source(value: Any, prefix: str) -> List[str]:
    if value is None or isinstance(value, str):
        return []
    if not isinstance(value, dict):
        return [f"{prefix} must be a path string or an object"]
    # IndexSource decodes every occurrence as Option<String>; an invalid
    # early value cannot be rescued by a later valid duplicate.
    pairs = value.pairs if isinstance(value, _Object) else value.items()
    invalid = {
        key
        for key, member in pairs
        if key in SOURCE_FIELDS and member is not None and not isinstance(member, str)
    }
    return [f"{prefix}.{key} must be a string or null" for key in sorted(invalid)]


def catalog_type_errors(data: Dict[str, Any]) -> List[str]:
    """Validate the whole typed catalog before per-entry installability."""
    errors = _duplicates(data, CATALOG_FIELDS)
    errors.extend(_name(data, "Marketplace catalog "))
    errors.extend(_strings(data, frozenset({"description"}), "Marketplace catalog "))
    errors.extend(_person(data.get("owner"), "owner", owner=True))
    entries = data.get("plugins", [])
    if not isinstance(entries, list):
        return errors + ["'plugins' must be an array"]
    for index, entry in enumerate(entries):
        prefix = f"plugins[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{prefix} must be an object")
            continue
        errors.extend(_duplicates(entry, ENTRY_FIELDS, prefix + "."))
        errors.extend(_name(entry, prefix + " "))
        errors.extend(_strings(entry, ENTRY_STRINGS, prefix + "."))
        errors.extend(_person(entry.get("author"), prefix + ".author"))
        errors.extend(_source(entry.get("source"), prefix + ".source"))
        for key in sorted(ENTRY_LISTS):
            if key not in entry:
                continue
            value = entry[key]
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                errors.append(f"{prefix}.{key} must be an array of strings")
    return errors
