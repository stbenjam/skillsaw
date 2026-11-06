"""Native theme declarations from OpenClaw v2026.11.1's manifest-themes.ts.

Only declarations belong to the manifest loading contract. Missing or invalid
theme JSON/SVG files omit a theme with a warning, rather than rejecting a plugin.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import json5

from skillsaw.formats.openclaw import MAX_MANIFEST_BYTES
from skillsaw.utils import cached_file_read

MAX_THEMES = 32
MAX_ARTWORK = 8
THEME_FIELDS = frozenset({"id", "name", "description", "source", "icons", "hats", "critters"})
ARTWORK_KINDS = ("icons", "hats", "critters")
CRITTER_FIELDS = frozenset({"source", "title", "crossMs"})
BUILTIN_ICONS = frozenset({"claw", "mark"})
BUILTIN_HATS = frozenset({"fedora", "crown", "santa", "party", "pumpkin"})
BUILTIN_CRITTERS = frozenset({"penguin", "fedora"})
LOCAL_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
ARTWORK_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")
PLUGIN_ID = re.compile(r"@?[a-z0-9][a-z0-9._-]*(?:/[a-z0-9][a-z0-9._-]*)*", re.I | re.ASCII)
ASSET_PATH = re.compile(r"(?:[a-z0-9_-][a-z0-9._-]*/)*[a-z0-9_-][a-z0-9._-]*", re.I | re.ASCII)
# JavaScript String.trim() differs from Python for NEL and control separators.
_JS_WHITESPACE = "\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"


def _js_length(value: str) -> int:
    return len(value.encode("utf-16-le", errors="surrogatepass")) // 2


def _asset_path(value: object, extension: str) -> bool:
    if not isinstance(value, str):
        return False
    path = value[2:] if value.startswith("./") else value
    return path.lower().endswith(extension) and ASSET_PATH.fullmatch(path) is not None


def _display_text(value: object, limit: int) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip(_JS_WHITESPACE))
        and _js_length(value.strip(_JS_WHITESPACE)) <= limit
        and not any(ord(char) < 32 or ord(char) == 127 for char in value)
    )


def _artwork_error(theme: dict, label: str) -> str | None:
    for kind, builtin in (
        ("icons", BUILTIN_ICONS),
        ("hats", BUILTIN_HATS),
        ("critters", BUILTIN_CRITTERS),
    ):
        if kind not in theme:
            continue
        entries = theme[kind]
        if not isinstance(entries, dict) or len(entries) > MAX_ARTWORK:
            return f"'{label}.{kind}' must be an object with at most {MAX_ARTWORK} entries"
        for identifier, value in entries.items():
            if ARTWORK_ID.fullmatch(identifier) is None or identifier in builtin:
                return f"'{label}.{kind}' needs lowercase artwork IDs of 1–32 characters outside the built-in catalog"
            if kind != "critters":
                source = value
            else:
                if not isinstance(value, dict) or value.keys() - CRITTER_FIELDS:
                    return f"'{label}.critters' entries must be objects with only source, title, and crossMs"
                source = value.get("source")
                if "title" in value:
                    title = value["title"]
                    if (
                        not isinstance(title, str)
                        or _js_length(title) > 60
                        or any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in title)
                    ):
                        return f"'{label}.critters' titles must be strings of at most 60 printable characters"
                if "crossMs" in value:
                    crossing = value["crossMs"]
                    if (
                        isinstance(crossing, bool)
                        or not isinstance(crossing, (int, float))
                        or not 5000 <= crossing <= 90000
                        or crossing != int(crossing)
                    ):
                        return (
                            f"'{label}.critters' crossMs must be an integer from 5000 through 90000"
                        )
            if not _asset_path(source, ".svg"):
                return f"'{label}.{kind}' sources must be relative SVG paths inside the plugin root"
    return None


class _Pairs(list):
    """Retain every JSON/JSON5 object property, including overwritten values."""


@cached_file_read
def _duplicate_artwork_error(path: Path) -> str | None:
    # Only theme declarations with artwork need a second, duplicate-preserving
    # parse. The normal JSON5 reader deliberately keeps last-value semantics.
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_MANIFEST_BYTES + 1)
        if len(raw) > MAX_MANIFEST_BYTES:
            return None  # The native manifest reader owns size/syntax failures.
        content = raw.decode("utf-8-sig")
        try:
            root = json.loads(content, object_pairs_hook=_Pairs)
        except ValueError:
            root = json5.loads(content, object_pairs_hook=_Pairs)
    except (OSError, ValueError, RecursionError, OverflowError):
        return None
    if not isinstance(root, _Pairs):
        return None
    for key, themes in root:
        if key != "themes" or not isinstance(themes, list) or isinstance(themes, _Pairs):
            continue
        for theme in themes:
            if not isinstance(theme, _Pairs):
                continue
            for kind, entries in theme:
                if kind not in ARTWORK_KINDS or not isinstance(entries, _Pairs):
                    continue
                seen = set()
                for identifier, _ in entries:
                    if identifier in seen:
                        return (
                            f"'themes.{kind}' contains duplicate artwork IDs; declare each ID once"
                        )
                    seen.add(identifier)
    return None


def theme_manifest_error(data: dict, path: Path) -> str | None:
    """Return the first rejected theme declaration, matching the native loader."""
    if "themes" not in data:
        return None
    themes = data["themes"]
    if not isinstance(themes, list) or len(themes) > MAX_THEMES:
        return f"'themes' must be an array with at most {MAX_THEMES} entries"
    identifier = data.get("id")
    if themes and isinstance(identifier, str) and identifier.strip():
        identifier = identifier.strip(_JS_WHITESPACE)
        if (
            identifier == "user"
            or identifier.startswith("user/")
            or _js_length(identifier + "/x") > 256
            or PLUGIN_ID.fullmatch(identifier) is None
        ):
            return "'themes' requires a portable plugin id outside the reserved user namespace"
    ids = set()
    has_artwork = False
    for index, theme in enumerate(themes):
        label = f"themes[{index}]"
        if not isinstance(theme, dict):
            return f"'{label}' must be an object"
        if theme.keys() - THEME_FIELDS:
            return (
                f"'{label}' supports only id, name, description, source, icons, hats, and critters"
            )
        local_id = theme.get("id")
        if not isinstance(local_id, str) or LOCAL_ID.fullmatch(local_id) is None or local_id in ids:
            return f"'{label}.id' must be a unique lowercase ID of 1–64 letters, digits, underscores, or hyphens, starting with a letter or digit"
        ids.add(local_id)
        for field, limit in (("name", 80), ("description", 320)):
            if not _display_text(theme.get(field), limit):
                return f"'{label}.{field}' must be non-empty text of at most {limit} characters without control characters"
        if not _asset_path(theme.get("source"), ".json"):
            return f"'{label}.source' must be a relative JSON path inside the plugin root"
        error = _artwork_error(theme, label)
        if error:
            return error
        has_artwork = has_artwork or any(kind in theme for kind in ARTWORK_KINDS)
    return _duplicate_artwork_error(path) if has_artwork else None
