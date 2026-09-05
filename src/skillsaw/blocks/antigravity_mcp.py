"""Antigravity MCP's ordered Go JSON view, independent of shape lint gates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, NoReturn, Optional, Tuple

from skillsaw.formats.antigravity import mcp_field_name
from skillsaw.utils import read_text


class _Object(dict):
    """Keep field occurrences for Go's retained type errors within a server."""

    def __init__(self, pairs):
        super().__init__(pairs)
        self.pairs = pairs


def field_occurrences(value: Dict[str, Any]) -> Iterable[Tuple[str, Any]]:
    """Original fields, including duplicates, beside the effective decoded view."""
    return value.pairs if isinstance(value, _Object) else value.items()


def _server(value: Any) -> Any:
    # A null server decodes as an empty configuration, and stays in inventory.
    if value is None:
        return {}
    if not isinstance(value, _Object):
        return value
    result = _Object(value.pairs)
    result.clear()
    for spelling, child in value.pairs:
        key = mcp_field_name(spelling)
        if key in ("env", "headers", "oauth") and isinstance(child, dict):
            # These maps merge across repeated fields; null clears them.
            # Env/header names are arbitrary, case-sensitive map keys.
            if key == "oauth":
                child = {mcp_field_name(k, oauth=True): v for k, v in field_occurrences(child)}
            else:
                child = dict(child)
            previous = result.get(key)
            if isinstance(previous, dict):
                previous.update(child)
                child = previous
        result[key] = child
    return result


def _reject_constant(token: str) -> NoReturn:
    raise ValueError(f"{token} is not valid JSON")


def read_mcp_config(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    """Decode one MCP document without borrowing ProtoJSON manifest semantics.

    The root map and server-name map replace duplicate values. Only fields
    inside the surviving server use Go struct matching and typed-map merging.
    Retaining their original occurrences lets validation see a type error
    even when a later value replaces it. Unknown numeric fields may exceed
    Python float range: their JSON spelling is still valid and Go ignores them.
    """
    content = read_text(path)
    if content is None:
        return None, f"Failed to read {path.name}"
    try:
        data = json.loads(content, object_pairs_hook=_Object, parse_constant=_reject_constant)
        if data is None:
            return {}, None
        if isinstance(data, dict) and isinstance(data.get("mcpServers"), dict):
            data["mcpServers"] = {
                name: _server(value) for name, value in data["mcpServers"].items()
            }
        return data, None
    except ValueError as error:
        return None, str(error)
    except RecursionError:
        return None, "Nesting too deep to parse"
