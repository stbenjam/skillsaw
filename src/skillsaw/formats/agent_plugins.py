"""Constants and offline schema loading for supported Agent Plugins versions."""

from __future__ import annotations

import json
import re
from importlib import resources
from typing import Any, Dict, Optional

PLUGIN_SCHEMA_ID = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA_ID = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
SUPPORTED_AGENT_PLUGIN_SCHEMA_VERSIONS = ("1.0.0", "1.1.0")

_SCHEMA_ID_RE = re.compile(
    r"\Ahttps://agent-plugins\.org/schemas/([^/]+)/" r"(plugin|mcp)\.schema\.json\Z"
)
_SCHEMA_PACKAGES = {
    "1.0.0": "skillsaw.schemas.agent_plugins.v1_0_0",
    "1.1.0": "skillsaw.schemas.agent_plugins.v1_1_0",
}


def agent_plugin_schema_version(value: object, kind: str) -> Optional[str]:
    """Return the declared Agent Plugins version for *kind*, if recognizable."""
    if not isinstance(value, str):
        return None
    match = _SCHEMA_ID_RE.fullmatch(value)
    if match is None or match.group(2) != kind:
        return None
    return match.group(1)


def is_agent_plugin_schema(value: object, kind: str) -> bool:
    """Whether *value* is a canonical Agent Plugins schema-shaped identifier."""
    return agent_plugin_schema_version(value, kind) is not None


def supported_agent_plugin_schema_version(value: object, kind: str) -> Optional[str]:
    """Return the declared version when its canonical schema is bundled."""
    version = agent_plugin_schema_version(value, kind)
    return version if version in _SCHEMA_PACKAGES else None


def agent_plugin_schema_id(version: str, kind: str) -> str:
    """Return the canonical schema identifier for a supported version and kind."""
    if version not in _SCHEMA_PACKAGES:
        raise ValueError(f"Unsupported Agent Plugins schema version: {version}")
    if kind not in {"plugin", "mcp"}:
        raise ValueError(f"Unsupported Agent Plugins schema kind: {kind}")
    return f"https://agent-plugins.org/schemas/{version}/{kind}.schema.json"


def load_agent_plugin_schema(filename: str, version: str = "1.0.0") -> Dict[str, Any]:
    """Load one versioned bundled schema without network access.

    Agent Plugins clients select locally supported schemas from ``$schema``;
    the specification explicitly forbids retrieving a schema while loading a
    package. Keeping this helper in the format layer also lets discovery and
    rules share identifiers without importing one another.
    """
    try:
        package = _SCHEMA_PACKAGES[version]
    except KeyError as error:
        raise ValueError(f"Unsupported Agent Plugins schema version: {version}") from error
    resource = resources.files(package).joinpath(filename)
    with resource.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict):  # pragma: no cover - packaged invariant
        raise RuntimeError(f"Bundled Agent Plugins schema {filename!r} is not an object")
    return data
