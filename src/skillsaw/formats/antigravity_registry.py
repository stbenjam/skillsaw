"""The measured JSONC registry decoder shared by discovery and config blocks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, NoReturn, Optional, Tuple

from skillsaw.formats.antigravity import REGISTRY_ENTRY_FIELDS, REGISTRY_FIELDS
from skillsaw.utils import read_text, strip_jsonc


class _Object(dict):
    def __init__(self, pairs):
        super().__init__(pairs)
        self.pairs = pairs


class _Entries(list):
    """Keep truncated PathEntry slots for a later nonempty array occurrence."""

    def __init__(self, values, previous):
        super().__init__(values)
        self.retained = values + previous[len(values) :] if values else []


class RegistryData(dict):
    """Effective fields, plus type errors retained from replaced occurrences."""

    def __init__(self):
        super().__init__()
        self.decode_errors: List[Tuple[str, str]] = []


def _field(spelling: str, names) -> str:
    # Go's simple fold recognizes long s but does not expand sharp s.
    folded = spelling.lower().replace("ſ", "s")
    return folded if folded in names else spelling


def _strings(value: Any, previous: Any, where: str, errors) -> Any:
    if value is None:
        return None
    if not isinstance(value, list):
        errors.append((where, "must be an array of strings"))
        return value
    old = previous if isinstance(previous, list) else []
    result = []
    for index, child in enumerate(value):
        if child is None:
            child = old[index] if index < len(old) else ""
        elif not isinstance(child, str):
            errors.append((f"{where}[{index}]", "must be a string"))
        result.append(child)
    return result


def _entries(value: Any, previous: Any, where: str, errors) -> Any:
    if value is None:
        return None
    if not isinstance(value, list):
        errors.append((where, "must be an array"))
        return value
    old = previous.retained if isinstance(previous, _Entries) else []
    result = []
    for index, item in enumerate(value):
        location = f"{where}[{index}]"
        prior = old[index] if index < len(old) else None
        entry = dict(prior) if isinstance(prior, dict) else {}
        if item is not None and not isinstance(item, _Object):
            errors.append((location, "must be an object with a string 'path'"))
        elif isinstance(item, _Object):
            for spelling, child in item.pairs:
                key = _field(spelling, REGISTRY_ENTRY_FIELDS)
                if key == "path":
                    if child is None:
                        continue  # A null string retains the prior decoded path.
                    if not isinstance(child, str):
                        errors.append(
                            (location, f"must have a string 'path'; '{spelling}' must be a string")
                        )
                elif key in ("include_only", "exclude"):
                    child = _strings(child, entry.get(key), f"{location}.{spelling}", errors)
                entry[key] = child
        result.append(entry)
    return _Entries(result, old)


def _decode(value: Any) -> Any:
    if value is None:
        return RegistryData()
    if not isinstance(value, _Object):
        return value
    result = RegistryData()
    for spelling, child in value.pairs:
        key = _field(spelling, REGISTRY_FIELDS)
        if key in REGISTRY_FIELDS:
            # Go reuses corresponding PathEntry values across nonempty arrays.
            # An empty array or null clears them before a later occurrence.
            child = _entries(child, result.get(key), spelling, result.decode_errors)
        result[key] = child
    return result


def _reject_constant(token: str) -> NoReturn:
    raise ValueError(f"{token} is not valid JSON")


def read_registry(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    """Read host fields without applying its Go contract to plugin manifests."""
    content = read_text(path)
    if content is None:
        return None, f"Failed to read {path.name}"
    try:
        try:
            data = json.loads(content, object_pairs_hook=_Object, parse_constant=_reject_constant)
        except ValueError:
            data = json.loads(
                strip_jsonc(content), object_pairs_hook=_Object, parse_constant=_reject_constant
            )
        return _decode(data), None
    except ValueError as error:
        return None, str(error)
    except RecursionError:
        return None, "Nesting too deep to parse"
