"""Select portable identity and the effective OpenAI plugin overlay.

The released Codex 0.154.0 reader chooses an object-valued
``extensions.com.openai`` before the compatibility manifest. Portable
skills and MCP always come from the package's fixed paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from skillsaw.formats.agent_plugins import (
    load_agent_plugin_schema,
    supported_agent_plugin_schema_version,
)
from skillsaw.paths import contained_resolve, safe_is_file, safe_resolve
from skillsaw.utils import read_json

OPENAI_EXTENSION = "com.openai"
OPENAI_OVERLAY_FIELDS = ("apps", "hooks", "interface")
# Codex 0.154.0's utils/plugins/src/plugin_namespace.rs recognizes 1.0.0
# only. Skillsaw also bundles the 1.1.0 draft for other portable readers;
# that does not make it a schema this released host can load.
CODEX_PORTABLE_SCHEMA_VERSIONS = ("1.0.0",)


def portable_manifest(plugin_dir: Path) -> Optional[dict[str, Any]]:
    """A supported, contained portable manifest, without claiming a host."""
    root = safe_resolve(plugin_dir)
    if root is None:
        return None
    path = contained_resolve(plugin_dir / "plugin.json", root)
    if path is None or not safe_is_file(path):
        return None
    data, error = read_json(path)
    if error or not isinstance(data, dict):
        return None
    version = supported_agent_plugin_schema_version(data.get("$schema"), "plugin")
    if version not in CODEX_PORTABLE_SCHEMA_VERSIONS:
        return None
    return data


def openai_extension(data: dict[str, Any]) -> Optional[dict[str, Any]]:
    """An object extension wins even when empty; other values fall back."""
    extensions = data.get("extensions")
    value = extensions.get(OPENAI_EXTENSION) if isinstance(extensions, dict) else None
    return value if isinstance(value, dict) else None


def declares_openai_extension(plugin_dir: Path) -> bool:
    data = portable_manifest(plugin_dir)
    return data is not None and openai_extension(data) is not None


def portable_manifest_is_usable(plugin_dir: Path) -> bool:
    """A portable entry may not rely on an escaping compatibility overlay."""
    from skillsaw.formats.codex import codex_marker_escapes

    data = portable_manifest(plugin_dir)
    return data is not None and (
        openai_extension(data) is not None or not codex_marker_escapes(plugin_dir)
    )


@lru_cache(maxsize=None)
def _name_validator(version: str):
    from jsonschema.validators import validator_for

    schema = load_agent_plugin_schema("plugin.schema.json", version)
    return validator_for(schema)(schema["properties"]["name"])


def portable_name_matches(plugin_dir: Path, name: str) -> bool:
    """A catalog may use the portable identifier, including its dots."""
    data = portable_manifest(plugin_dir)
    if data is None or data.get("name") != name:
        return False
    version = supported_agent_plugin_schema_version(data.get("$schema"), "plugin")
    return version is not None and _name_validator(version).is_valid(name)


@dataclass(frozen=True)
class CodexManifestView:
    """Effective fields and the file containing the selected overlay."""

    path: Path
    data: dict[str, Any]
    portable: bool = False


def codex_manifest_view(plugin_dir: Path) -> CodexManifestView:
    compatibility_path = plugin_dir / ".codex-plugin" / "plugin.json"
    portable = portable_manifest(plugin_dir)
    extension = openai_extension(portable) if portable is not None else None
    if extension is not None:
        path, overlay = plugin_dir / "plugin.json", extension
    else:
        path = compatibility_path
        root = safe_resolve(plugin_dir)
        contained = contained_resolve(path, root) if root is not None else None
        data, error = read_json(contained) if contained is not None else (None, None)
        overlay = data if not error and isinstance(data, dict) else {}
        if portable is not None and not safe_is_file(path):
            path = plugin_dir / "plugin.json"
    if portable is None:
        return CodexManifestView(path, overlay)
    # Root identity is canonical; an overlay's name/version cannot replace
    # it, and its skills/mcpServers cannot augment the fixed components.
    data = {
        key: portable[key]
        for key in (
            "name",
            "version",
            "description",
            "author",
            "homepage",
            "repository",
            "license",
            "keywords",
        )
        if key in portable
    }
    data.update({key: overlay[key] for key in OPENAI_OVERLAY_FIELDS if key in overlay})
    return CodexManifestView(path, data, portable=True)
