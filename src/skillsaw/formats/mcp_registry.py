"""MCP Registry ``server.json`` format constants and offline schema loading."""

from __future__ import annotations

import json
import re
from importlib import resources
from typing import Any, Dict, Optional

MCP_REGISTRY_SCHEMA_VERSION = "2025-12-11"
MCP_REGISTRY_SCHEMA_ID = (
    "https://static.modelcontextprotocol.io/schemas/"
    f"{MCP_REGISTRY_SCHEMA_VERSION}/server.schema.json"
)
_REMOTE_TRANSPORTS = frozenset({"streamable-http", "sse"})

_SCHEMA_ID_RE = re.compile(
    r"\Ahttps://static\.modelcontextprotocol\.io/schemas/"
    r"([A-Za-z0-9_~.-]+)/server\.schema\.json\Z"
)


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


def load_mcp_registry_schema() -> Dict[str, Any]:
    """Load the bundled released schema without making a network request."""
    resource = resources.files("skillsaw.schemas.mcp_registry.v2025_12_11").joinpath(
        "server.schema.json"
    )
    with resource.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict):  # pragma: no cover - packaged invariant
        raise RuntimeError("Bundled MCP Registry server schema is not an object")
    return data
