"""Shared value representations in Grok's TOML configuration decoders."""

from __future__ import annotations

from typing import Any, Optional, Sequence


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


def struct_fields(value: Any, fields: Sequence[str], required: int = 0) -> Any:
    """Normalize a measured Grok TOML positional struct; keep invalid input.

    Field order and the required positional prefix come from the owning
    struct. Mapping inputs keep their ordinary named-field validation.
    """
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list) and required <= len(value) <= len(fields):
        return dict(zip(fields, value))
    return value
