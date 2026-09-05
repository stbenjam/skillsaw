"""Antigravity hook fields and ordered decoding, separate from its MCP reader."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterator, NoReturn, Optional, Tuple

from skillsaw.formats.antigravity import hook_field_name
from skillsaw.utils import read_text

# Native conflict probes prove that null retains these prior string values.
# Keep the established nullable view of enabled/timeout; metadata listing
# does not expose their effective values after a repeated null.
_RETAIN_NULL = frozenset({"type", "command", "prompt", "model", "matcher"})


class _Object(dict):
    def __init__(self, pairs):
        super().__init__(pairs)
        self.pairs = pairs
        self.occurrences = []
        self.spellings = {}
        self.has_repeated_fields = False


def field_items(value: Dict[str, Any], *, history: bool = False) -> Iterator[Tuple[str, str, Any]]:
    """Canonical key, source spelling and value, optionally before replacement."""
    if history and isinstance(value, _Object):
        yield from value.occurrences
    else:
        spellings = value.spellings if isinstance(value, _Object) else {}
        for key, child in value.items():
            yield key, spellings.get(key, key), child


def _decode(value: Any, kind: str) -> Tuple[Any, bool]:
    if isinstance(value, list):
        decoded = [_decode(child, kind) for child in value]
        return [child for child, _ in decoded], any(repeated for _, repeated in decoded)
    if not isinstance(value, _Object):
        return value, False
    result = _Object([])
    for spelling, child in value.pairs:
        key = (
            spelling
            if kind == "root"
            else hook_field_name(spelling, entry=kind in ("entry", "handler"))
        )
        repeated = False
        if kind == "root":
            child, repeated = _decode(child, "spec")
        elif kind == "spec" and key != "enabled":
            if isinstance(child, list):
                child, repeated = _decode(child, "entry")
        elif kind == "entry" and key == "hooks" and isinstance(child, list):
            child, repeated = _decode(child, "handler")
        result.has_repeated_fields |= repeated or key in result
        result.occurrences.append((key, spelling, child))
        if kind in ("entry", "handler") and key in _RETAIN_NULL and child is None and key in result:
            continue
        result[key] = child
        result.spellings[key] = spelling
    return result, result.has_repeated_fields


def _reject_constant(token: str) -> NoReturn:
    raise ValueError(f"{token} is not valid JSON")


def read_hooks_config(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    """Read effective fields and retain earlier objects for type-error validation."""
    content = read_text(path)
    if content is None:
        return None, f"Failed to read {path.name}"
    try:
        data = json.loads(content, object_pairs_hook=_Object, parse_constant=_reject_constant)
        if data is None:
            return {}, None
        # A root array remains a wrong-typed root, rather than a handler list.
        return _decode(data, "root")[0] if isinstance(data, dict) else data, None
    except ValueError as error:
        return None, str(error)
    except RecursionError:
        return None, "Nesting too deep to parse"
