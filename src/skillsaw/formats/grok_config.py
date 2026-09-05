"""Shared value representations in Grok's TOML configuration decoders."""

from __future__ import annotations

from typing import Any, Optional


def unit_enum_value(value: Any) -> Optional[str]:
    """Read the unit-enum forms accepted by Grok's TOML deserializer.

    Alongside a string, TOML accepts a single variant key with an empty
    table or array body: ``{ select = {} }`` or ``{ select = [] }``.
    A nonempty body or multiple keys rejects the enum.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and len(value) == 1:
        name, body = next(iter(value.items()))
        if isinstance(body, (dict, list)) and not body:
            return name
    return None
