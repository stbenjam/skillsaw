"""Antigravity's plugin.json JSONC manifest reader (agy 1.5.11+)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, NoReturn, Optional, Tuple

from skillsaw.utils import read_text, strip_jsonc


def _reject_constant(token: str) -> NoReturn:
    raise ValueError(f"{token} is not valid JSON")


def read_plugin_manifest(path: Path) -> Tuple[Optional[Any], Optional[str]]:
    """Read an Antigravity ``plugin.json`` manifest as JSONC.

    Measured against ``agy`` 1.5.11: the loader strips a leading UTF-8 BOM,
    accepts JSONC comments and trailing commas, decodes into
    ``map[string]jsontext.Value`` (exact-case keys, last value wins for a
    repeated key), treats a ``null`` root as an empty manifest, and still
    rejects non-JSON constants such as ``NaN`` and ``Infinity``.
    """
    content = read_text(path)
    if content is None:
        return None, f"Failed to read {path.name}"
    try:
        try:
            data = json.loads(content, parse_constant=_reject_constant)
        except ValueError:
            data = json.loads(strip_jsonc(content), parse_constant=_reject_constant)
        if data is None:
            return {}, None
        return data, None
    except ValueError as error:
        return None, str(error)
    except RecursionError:
        return None, "Nesting too deep to parse"
