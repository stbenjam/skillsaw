"""Grok 1.0.13's optional display-index decoder (not install metadata).

PluginCatalog/CatalogEntry and PluginComponents/ComponentItem at pinned
72a61251fcffb464bcc687aeb5a998e5a98ec0c9. A typed failure drops the whole
index. Unknown fields stay open; struct duplicates and map entries differ.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from skillsaw.diagnostics import safe_display
from skillsaw.utils import has_utf8_bom, read_text

CATEGORIES = ("skills", "commands", "agents", "mcpServers", "hooks", "lspServers")


class _Object(dict):
    def __init__(self, pairs):
        super().__init__(pairs)
        self.pairs = pairs


def _reject_constant(token: str) -> None:
    raise ValueError(f"non-finite JSON number: {token}")


def _struct(value: Any, fields: tuple, required: int, label: str) -> Dict[str, Any]:
    # Native serde accepts positional struct arrays as well as objects.
    if isinstance(value, list) and required <= len(value) <= len(fields):
        return dict(zip(fields, value))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object or a valid field array")
    seen = set()
    for key, _member in getattr(value, "pairs", value.items()):
        if key in fields:
            if key in seen:
                raise ValueError(f"Duplicate display-index field '{label}.{key}'")
            seen.add(key)
    return value


def _decode(data: Any) -> Dict[str, Any]:
    data = _struct(data, ("version", "plugins"), 1, "index")
    version = data.get("version")
    if type(version) is not int or version != 1:
        raise ValueError("'version' must be the supported integer 1")
    plugins = data.get("plugins", {})
    if not isinstance(plugins, dict):
        raise ValueError("'plugins' must be an object keyed by plugin name")
    decoded = {}
    # A HashMap keeps the last duplicate entry but decodes earlier values too.
    for key, raw in getattr(plugins, "pairs", plugins.items()):
        label = f"plugins[{safe_display(repr(key))}]"
        entry = _struct(raw, ("sha", "components"), 2, label)
        sha = entry.get("sha")
        if sha is not None and not isinstance(sha, str):
            raise ValueError(f"{label}.sha must be a string or null")
        if "components" not in entry:
            raise ValueError(f"{label} is missing required 'components'")
        components = _struct(entry["components"], CATEGORIES, 0, label + ".components")
        normalized = {}
        for category in CATEGORIES:
            values = components.get(category, [])
            prefix = f"{label}.components.{category}"
            if not isinstance(values, list):
                raise ValueError(f"{prefix} must be an array")
            items = []
            for number, value in enumerate(values):
                item_label = f"{prefix}[{number}]"
                item = _struct(value, ("name", "description"), 1, item_label)
                if not isinstance(item.get("name"), str):
                    raise ValueError(f"{item_label}.name must be a string")
                description = item.get("description")
                if description is not None and not isinstance(description, str):
                    raise ValueError(f"{item_label}.description must be a string or null")
                items.append(dict(item))
            normalized[category] = items
        decoded[key] = {"sha": sha, "components": normalized}
    return decoded


def read_display_index(path: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Return the decoded plugin map, or one whole-index failure message."""
    if has_utf8_bom(path):
        return None, "Invalid JSON: UTF-8 BOM is not accepted by Grok's display index loader"
    content = read_text(path)
    if content is None:
        return None, "Invalid JSON: could not read file"
    try:
        data = json.loads(content, object_pairs_hook=_Object, parse_constant=_reject_constant)
    except (ValueError, RecursionError) as exc:
        return None, f"Invalid JSON: {exc}"
    try:
        return _decode(data), None
    except ValueError as exc:
        return None, f"Invalid display index: {exc}"
