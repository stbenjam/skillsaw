"""Kiro's documented shared subset, without permission-dialect inference.

Contracts: CLI 2.x JSON and IDE 1.x / CLI V3 JSON or Markdown, as documented
2026-10-10. The historical agent-v1 schema in amazon-q-developer-cli
v1.19.7 corroborates nullable legacy fields; it is not a V3 schema.
See docs/kiro.md for sources and intentionally unvalidated fields.
"""

from types import MappingProxyType
from typing import Any, Iterator, Tuple

AGENT_STRING_FIELDS = ("name", "description", "prompt", "model", "welcomeMessage")
AGENT_LIST_FIELDS = ("tools", "excludedTools")
AGENT_BOOL_FIELDS = ("includeMcpJson", "includePowers")
MCP_STRING_FIELDS = ("command", "url")
MCP_LIST_FIELDS = ("args", "autoApprove", "disabledTools", "oauthScopes")
MCP_MAP_FIELDS = ("env", "headers")
MCP_CREDENTIAL_KEY_ALIASES = MappingProxyType({"clientSecret": "client_secret"})


def agent_field_problems(data: dict) -> Iterator[Tuple[str, str]]:
    """Validate only documented containers/scalars common to supported forms."""
    for key in AGENT_STRING_FIELDS:
        # Legacy Option<String> accepts null. Do not infer V3 from an
        # omitted permissions block, or reject a working 2.x profile.
        if key in data and data[key] is not None and not isinstance(data[key], str):
            yield key, f"'{key}' must be a string"
    for key in AGENT_LIST_FIELDS:
        if key in data and not string_list(data[key]):
            yield key, f"'{key}' must be an array of strings"
    for key in AGENT_BOOL_FIELDS:
        if key in data and not isinstance(data[key], bool):
            yield key, f"'{key}' must be a boolean"
    if "resources" in data:
        resources = data["resources"]
        if not isinstance(resources, list) or any(
            not isinstance(entry, (str, dict)) for entry in resources
        ):
            yield "resources", "'resources' must be an array of URI strings or resource objects"
    if "mcpServers" in data and not isinstance(data["mcpServers"], dict):
        yield "mcpServers", "'mcpServers' must be an object"


def string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def mcp_field_problems(data: dict) -> Iterator[Tuple[str, str]]:
    """Check field shapes without assuming a complete, active transport.

    Kiro documents partial entries (disabled/disabledTools overrides), and
    legacy HTTP records can carry an empty command. Connection resolution,
    transport selection and OAuth negotiation belong to the host.
    """
    for key in MCP_STRING_FIELDS:
        if key in data and data[key] is not None and not isinstance(data[key], str):
            yield key, f"'{key}' must be a string"
    for key in MCP_LIST_FIELDS:
        if key in data and not string_list(data[key]):
            yield key, f"'{key}' must be an array of strings"
    for key in MCP_MAP_FIELDS:
        value = data.get(key)
        if value is not None and (
            not isinstance(value, dict)
            or any(not isinstance(k, str) or not isinstance(v, str) for k, v in value.items())
        ):
            yield key, f"'{key}' must be an object of strings"
    if "disabled" in data and not isinstance(data["disabled"], bool):
        yield "disabled", "'disabled' must be a boolean"
    if data.get("oauth") is not None and not isinstance(data["oauth"], dict):
        yield "oauth", "'oauth' must be an object"
