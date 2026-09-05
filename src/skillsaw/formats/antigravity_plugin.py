"""Antigravity's ProtoJSON manifest grammar, separate from Go config readers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, NoReturn, Optional, Tuple

from skillsaw.formats.antigravity import PLUGIN_MESSAGE_FIELDS
from skillsaw.utils import read_text

_KNOWN_FIELDS = frozenset(field for field, _, _ in PLUGIN_MESSAGE_FIELDS)


class _Object(dict):
    def __init__(self, pairs):
        super().__init__(pairs)
        self.pairs = pairs


def _check_strings(value: Any) -> None:
    # Token validity applies even to discarded metadata and earlier duplicates.
    # Walk iterators so nested arrays do not require recursion or a breadth copy.
    pending = [iter((value,))]
    while pending:
        try:
            child = next(pending[-1])
        except StopIteration:
            pending.pop()
            continue
        if isinstance(child, str):
            if not child.isascii():
                try:
                    child.encode("utf-8")
                except UnicodeEncodeError as error:
                    raise ValueError("invalid Unicode surrogate in JSON string") from error
        elif isinstance(child, _Object):
            pending.append(iter(child.pairs))
        elif isinstance(child, (list, tuple)):
            pending.append(iter(child))


def _reject_constant(token: str) -> NoReturn:
    raise ValueError(f"{token} is not valid JSON")


def read_plugin_manifest(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    """Reject repeated known root fields while allowing discarded metadata."""
    content = read_text(path)
    if content is None:
        return None, f"Failed to read {path.name}"
    try:
        data = json.loads(content, object_pairs_hook=_Object, parse_constant=_reject_constant)
        _check_strings(data)
        if isinstance(data, _Object):
            seen = set()
            for key, _ in data.pairs:
                if key not in _KNOWN_FIELDS:
                    continue
                if key in seen:
                    raise ValueError(f'duplicate JSON object key: "{key}"')
                seen.add(key)
        return data, None
    except ValueError as error:
        return None, str(error)
    except RecursionError:
        return None, "Nesting too deep to parse"
