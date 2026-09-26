"""Native OpenClaw authoring contracts, pinned to upstream 912b21b98581.

Source: https://github.com/openclaw/openclaw/blob/912b21b98581c0be3baad87fe3686b64d69fffeb/src/plugins/manifest.ts
Native manifests are JSON5; package.json remains ordinary JSON.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import json5

from skillsaw.paths import Resolver, contained_resolve, safe_is_file, safe_resolve
from skillsaw.utils import _reject_non_finite, cached_file_read, strip_jsonc

MANIFEST = "openclaw.plugin.json"
# MAX_PLUGIN_MANIFEST_BYTES in the pinned native loader, before any parsing.
MAX_MANIFEST_BYTES = 256 * 1024
# DEFAULT_PLUGIN_METADATA_MAX_BYTES in plugin-cache-files.ts; packages use it.
MAX_PACKAGE_BYTES = 16 * 1024 * 1024
_JSONC_TOKEN = re.compile(r"//|\S")


def _needs_json5_comma_check(content: str) -> bool:
    """Find leading commas in one pass, skipping strings and line comments."""
    position = 0
    previous = ""
    while match := _JSONC_TOKEN.search(content, position):
        token = match.group()
        position = match.end()
        if token == '"':
            try:
                _, position = json.decoder.scanstring(content, position)
            except ValueError:
                # JSON5 strings may require syntax the JSON scanner rejects.
                return True
            previous = '"'
        elif token == "//":
            newline = content.find("\n", position)
            if newline == -1:
                return False
            position = newline + 1
        else:
            if token == "," and previous in ("{", "["):
                return True
            previous = token
    return False


@cached_file_read
def read_manifest(path: Path) -> tuple[object | None, str | None]:
    """Bound the read, then prefer JSON/JSONC before the slower JSON5 parser."""
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_MANIFEST_BYTES + 1)
    except FileNotFoundError:
        return None, f"Missing {MANIFEST}; create it with 'id' and 'configSchema'"
    except OSError:
        return None, f"Cannot read {MANIFEST}; check the file and its permissions"
    if len(raw) > MAX_MANIFEST_BYTES:
        return None, f"Manifest exceeds OpenClaw's {MAX_MANIFEST_BYTES}-byte limit"
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None, "Manifest must be UTF-8 text"
    try:
        return json.loads(content), None
    except RecursionError:
        return None, "Manifest nesting exceeds the parser limit"
    except ValueError:
        pass
    # The JSONC scanner tolerates unfinished block comments and only treats
    # LF as a line-comment terminator. It also removes commas in empty
    # containers, which JSON5 rejects. These forms need the native parser.
    if not any(marker in content for marker in ("/*", "\r", "\u2028", "\u2029")) and not (
        "," in content and _needs_json5_comma_check(content)
    ):
        try:
            return json.loads(strip_jsonc(content)), None
        except RecursionError:
            return None, "Manifest nesting exceeds the parser limit"
        except ValueError:
            pass
    try:
        return json5.loads(content), None
    except (ValueError, RecursionError, OverflowError) as exc:
        return None, f"Cannot parse JSON5 manifest: {exc}"


def read_package_text(path: Path) -> tuple[str | None, str | None]:
    """Bound package probes without caching ordinary, negative candidates."""
    try:
        with path.open("rb") as stream:
            # Most package probes are tiny negative candidates. Avoid reserving
            # a 16 MiB read buffer for every ordinary package in a monorepo.
            raw = stream.read(64 * 1024)
            if len(raw) == 64 * 1024:
                raw += stream.read(MAX_PACKAGE_BYTES + 1 - len(raw))
    except OSError:
        return None, "Cannot read package.json"
    if len(raw) > MAX_PACKAGE_BYTES:
        return None, f"package.json exceeds OpenClaw's {MAX_PACKAGE_BYTES}-byte limit"
    try:
        # The native package loader calls JSON.parse without stripping a BOM.
        return raw.decode("utf-8"), None
    except UnicodeDecodeError:
        return None, "package.json must be UTF-8 text"


@cached_file_read
def read_package(path: Path) -> tuple[object | None, str | None]:
    """Read native package metadata within the host's size bound."""
    content, error = read_package_text(path)
    if error:
        return None, error
    try:
        return json.loads(content, parse_constant=_reject_non_finite), None
    except (ValueError, RecursionError) as exc:
        return None, f"Cannot parse package.json: {exc}"


def contained_file(root: Path, name: str, *, resolve: Resolver = safe_resolve) -> bool:
    resolved = resolve(root)
    return (
        resolved is not None
        and contained_resolve(root / name, resolved, resolve) is not None
        and safe_is_file(root / name)
    )


def runtime_extensions(metadata: dict) -> tuple[list[str], str | None]:
    """Read explicit runtime paths using package-entry-resolution.ts's contract.

    On malformed mappings, retain valid paths for containment checks only;
    callers must not use them for runtime selection when an error is returned.
    """
    sources = metadata.get("extensions")
    # The loader reads runtime mappings only for explicit source entries.
    # Conventional fallback ignores this metadata; source shape errors belong
    # to the package validator.
    if (
        not isinstance(sources, list)
        or not sources
        or any(not isinstance(source, str) or not source.strip() for source in sources)
    ):
        return [], None
    values = metadata.get("runtimeExtensions")
    if not isinstance(values, list) or not values:
        return [], None
    entries = [value.strip() for value in values if isinstance(value, str) and value.strip()]
    if len(entries) != len(values):
        return entries, "'openclaw.runtimeExtensions' must contain only non-empty strings"
    if len(entries) != len(sources):
        return (
            entries,
            "'openclaw.runtimeExtensions' must have the same length as 'openclaw.extensions'",
        )
    return entries, None


def skill_roots(plugin: Path) -> list[Path]:
    """Only explicitly declared skill roots load; there is no skills/ fallback."""
    if not contained_file(plugin, MANIFEST):
        return []
    data, _ = read_manifest(plugin / MANIFEST)
    raw = data.get("skills") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    return [plugin / value.strip() for value in raw if isinstance(value, str) and value.strip()]


def _property_order(key: str) -> int:
    """Object.entries visits array-index properties first, in numeric order."""
    if key.isascii() and key.isdecimal() and len(key) <= 10:
        number = int(key)
        if str(number) == key and number < 2**32 - 1:
            return number
    # Stable sorting preserves insertion order for all other string keys.
    return 2**32


def inline_mcp_servers(plugin: Path, *, resolve: Resolver = safe_resolve) -> dict[str, Any] | None:
    """Expose exactly the servers retained by normalizeManifestMcpServers.

    The pinned manifest-capability-normalizers.ts trims server names and
    rejects empty names, prototype keys and non-object entries before the
    runtime sees them. This is host normalization, not Python dict protection.
    """
    if not contained_file(plugin, MANIFEST, resolve=resolve):
        return None
    data, _ = read_manifest(plugin / MANIFEST)
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        return None
    return {
        key.strip(): value
        for key, value in sorted(servers.items(), key=lambda item: _property_order(item[0]))
        if key.strip()
        and key.strip() not in {"__proto__", "prototype", "constructor"}
        and isinstance(value, dict)
    }
