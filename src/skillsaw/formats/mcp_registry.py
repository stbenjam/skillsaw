"""MCP Registry ``server.json`` format constants and offline schema loading."""

from __future__ import annotations

import json
import re
from importlib import resources
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional

MCP_REGISTRY_SCHEMA_PACKAGES: Mapping[str, str] = MappingProxyType(
    {
        "2025-12-11": "skillsaw.schemas.mcp_registry.v2025_12_11",
    }
)
MCP_REGISTRY_SCHEMA_VERSIONS = frozenset(MCP_REGISTRY_SCHEMA_PACKAGES)
# Registry schema versions are ISO dates, so lexical order identifies the
# newest bundled release while older entries remain available for validation.
MCP_REGISTRY_SCHEMA_VERSION = max(MCP_REGISTRY_SCHEMA_VERSIONS)
_REMOTE_TRANSPORTS = frozenset({"streamable-http", "sse"})

_SCHEMA_ID_RE = re.compile(
    r"\Ahttps://static\.modelcontextprotocol\.io/schemas/"
    r"([A-Za-z0-9_~.-]+)/server\.schema\.json\Z"
)


def mcp_registry_schema_id(version: str) -> str:
    """Return the canonical MCP Registry schema identifier for a version."""
    return "https://static.modelcontextprotocol.io/schemas/" f"{version}/server.schema.json"


MCP_REGISTRY_SCHEMA_ID = mcp_registry_schema_id(MCP_REGISTRY_SCHEMA_VERSION)


def mcp_registry_schema_version(value: object) -> Optional[str]:
    """Return the version in a canonical MCP Registry schema URL."""
    if not isinstance(value, str):
        return None
    match = _SCHEMA_ID_RE.fullmatch(value)
    return match.group(1) if match is not None else None


def is_mcp_registry_server(data: object) -> bool:
    """Whether parsed JSON is confidently an MCP Registry server document.

    The canonical schema URL is definitive. The structural fallback finds a
    publisher document whose required schema field is missing, while keeping a
    generic ``server.json`` out unless it carries the MCP Registry's identity
    fields and one of its package/remote entry shapes.
    """
    if not isinstance(data, dict):
        return False
    if mcp_registry_schema_version(data.get("$schema")) is not None:
        return True
    if not {"name", "description", "version"} <= data.keys():
        return False
    packages = data.get("packages")
    if isinstance(packages, list) and any(
        isinstance(package, dict) and {"registryType", "identifier", "transport"} <= package.keys()
        for package in packages
    ):
        return True
    remotes = data.get("remotes")
    return isinstance(remotes, list) and any(
        isinstance(remote, dict) and remote.get("type") in _REMOTE_TRANSPORTS and "url" in remote
        for remote in remotes
    )


def load_mcp_registry_schema(
    version: str = MCP_REGISTRY_SCHEMA_VERSION,
) -> Dict[str, Any]:
    """Load one bundled released schema without making a network request."""
    package = MCP_REGISTRY_SCHEMA_PACKAGES.get(version)
    if package is None:
        supported = ", ".join(sorted(MCP_REGISTRY_SCHEMA_VERSIONS))
        raise ValueError(
            f"Unsupported MCP Registry schema version {version!r}; "
            f"available versions: {supported}"
        )
    resource = resources.files(package).joinpath("server.schema.json")
    with resource.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict):  # pragma: no cover - packaged invariant
        raise RuntimeError("Bundled MCP Registry server schema is not an object")
    return data
