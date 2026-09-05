"""Grok 1.0.13's TOML MCP decoder, before setup and environment resolution.

The pinned config-types/mcp.rs deserializer tries Stdio before StreamableHttp.
A failed variant may fall through; fields outside the selected variant are
ignored. Common fields are decoded independently and cannot fall through.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from skillsaw.diagnostics import safe_display
from skillsaw.formats.grok_config import struct_fields, unit_enum_value

URL_FIELDS = ("url", "urlTemplate", "url_template")
_STDIO_FIELDS = {"command": "string", "args": "strings", "env": "string-map", "cwd": "string"}
_HTTP_FIELDS = {
    **dict.fromkeys(URL_FIELDS, "string"),
    "type": "string",
    "bearer_token_env_var": "string",
    "headers": "string-map",
    "oauth_client_id": "string",
    "oauth_client_secret_env_var": "string",
    "oauth_scopes": "strings",
}
_COMMON_FIELDS = {
    "enabled": "boolean",
    "startup_timeout_sec": "u64",
    "tool_timeout_sec": "u64",
    "tool_timeouts": "u64-map",
    "expose_image_base64": "boolean",
    "oauth": "table",
    "setup": "table",
}
# Rust str::trim uses Unicode White_Space, excluding Python's U+001C..U+001F.
_WHITESPACE = "\t\n\v\f\r \x85\xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"


def _type_name(value: Any) -> str:
    return {
        bool: "boolean",
        dict: "table",
        float: "float",
        int: "integer",
        list: "array",
        str: "string",
    }.get(type(value), type(value).__name__)


def _value_error(field: str, value: Any, kind: str) -> Optional[str]:
    label = f"'{safe_display(field)}'"
    if kind == "select":
        return None if unit_enum_value(value) == "select" else f"{label} must be 'select'"
    if kind in ("string", "boolean", "table"):
        expected = {"string": str, "boolean": bool, "table": dict}[kind]
        if isinstance(value, expected):
            return None
        return f"{label} must be a {kind}, got {_type_name(value)}"
    if kind in ("u64", "u16"):
        maximum = 2 ** int(kind[1:]) - 1
        if type(value) is int and 0 <= value <= maximum:
            return None
        return f"{label} must be an integer from 0 to {maximum}"
    if kind == "strings":
        if not isinstance(value, list):
            return f"{label} must be an array of strings, got {_type_name(value)}"
        if any(not isinstance(item, str) for item in value):
            return f"{label} must be an array of strings"
        return None
    if kind == "tables":
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            return f"{label} must be an array of tables"
        return None
    item_kind = "string" if kind == "string-map" else "u64"
    noun = "strings" if item_kind == "string" else "unsigned integers"
    if not isinstance(value, dict):
        return f"{label} must be a table of {noun}, got {_type_name(value)}"
    for key, item in value.items():
        problem = _value_error(f"{field}.{key}", item, item_kind)
        if problem is not None:
            if item_kind == "string":
                return f"{label} value for '{safe_display(key)}' must be a string, got {_type_name(item)}"
            return problem
    return None


def _fields(
    table: Mapping[str, Any],
    types: Mapping[str, str],
    prefix: str = "",
    required: Tuple[str, ...] = (),
) -> List[str]:
    problems = []
    for key in required:
        if key not in table:
            problems.append(f"'{prefix}{key}' is required")
    for key, kind in types.items():
        if key in table:
            error = _value_error(prefix + key, table[key], kind)
            if error is not None:
                problems.append(error)
    return problems


def _normalized_structs(server: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize the OAuth/setup structs whose TOML sequence forms load."""
    normalized = dict(server)
    if "oauth" in server:
        normalized["oauth"] = struct_fields(
            server["oauth"], ("clientId", "clientSecretEnvVar", "scopes", "callbackPort")
        )
    if "setup" not in server:
        return normalized
    setup = struct_fields(server["setup"], ("fields", "variables"))
    normalized["setup"] = setup
    if not isinstance(setup, dict):
        return normalized
    fields = setup.get("fields")
    if isinstance(fields, list):
        setup["fields"] = fields = [
            struct_fields(value, ("id", "label", "type", "required", "default", "options"), 3)
            for value in fields
        ]
        for value in fields:
            if isinstance(value, dict) and isinstance(value.get("options"), list):
                value["options"] = [
                    struct_fields(option, ("label", "value"), 2) for option in value["options"]
                ]
    for key in ("variables", "values"):
        variables = setup.get(key)
        if isinstance(variables, dict):
            setup[key] = {
                name: struct_fields(value, ("from", "map"), 2) for name, value in variables.items()
            }
    return normalized


def _nested_errors(server: Mapping[str, Any]) -> List[str]:
    problems = []
    oauth = server.get("oauth")
    if isinstance(oauth, dict):
        problems.extend(
            _fields(
                oauth,
                {
                    "clientId": "string",
                    "clientSecretEnvVar": "string",
                    "scopes": "strings",
                    "callbackPort": "u16",
                },
                "oauth.",
            )
        )
    setup = server.get("setup")
    if not isinstance(setup, dict):
        return problems
    problems.extend(
        _fields(setup, {"fields": "tables", "variables": "table", "values": "table"}, "setup.")
    )
    if "variables" in setup and "values" in setup:
        problems.append("'setup.variables' and its alias 'setup.values' cannot both be set")
    fields = setup.get("fields", [])
    if isinstance(fields, list):
        for position, value in enumerate(fields, 1):
            if not isinstance(value, dict):
                continue
            prefix = f"setup.fields[{position}]."
            problems.extend(
                _fields(
                    value,
                    {
                        "id": "string",
                        "label": "string",
                        "type": "select",
                        "required": "boolean",
                        "default": "string",
                        "options": "tables",
                    },
                    prefix,
                    ("id", "label", "type"),
                )
            )
            options = value.get("options", [])
            if isinstance(options, list):
                for index, option in enumerate(options, 1):
                    if isinstance(option, dict):
                        problems.extend(
                            _fields(
                                option,
                                {"label": "string", "value": "string"},
                                f"{prefix}options[{index}].",
                                ("label", "value"),
                            )
                        )
    for key in ("variables", "values"):
        variables = setup.get(key)
        if isinstance(variables, dict):
            for name, value in variables.items():
                prefix = f"setup.{key}.{safe_display(name)}"
                if not isinstance(value, dict):
                    problems.append(f"'{prefix}' must be a table")
                else:
                    problems.extend(
                        _fields(
                            value,
                            {"from": "string", "map": "string-map"},
                            prefix + ".",
                            ("from", "map"),
                        )
                    )
    return problems


def decode_mcp_server(server: Mapping[str, Any]) -> Tuple[Optional[str], List[str]]:
    """Return the decoded transport, or the reasons the server is rejected.

    Keep disabled and unresolved-setup definitions available to diagnostic
    consumers. They deserialize even when Grok does not connect to them.
    """
    server = _normalized_structs(server)
    common = _fields(server, _COMMON_FIELDS) + _nested_errors(server)
    stdio = _fields(server, _STDIO_FIELDS)
    urls = [key for key in URL_FIELDS if key in server]
    http = _fields(server, _HTTP_FIELDS)
    if len(urls) > 1:
        http.append("'url', 'urlTemplate' and 'url_template' are aliases; set only one")
    if "command" in server and not stdio:
        transport, connection = "stdio", "command"
    elif urls and not http:
        connection = urls[0]
        transport = (
            "sse"
            if server.get("type", "").lower() == "sse" or server[connection].endswith("/sse")
            else "http"
        )
    else:
        if "command" not in server and not urls:
            return None, common or ["declares neither 'command' nor 'url'"]
        return None, common + (stdio if "command" in server else []) + (http if urls else [])
    if common:
        return None, common
    if server.get("enabled", True) and not server[connection].strip(_WHITESPACE):
        return None, [f"'{connection}' is empty"]
    return transport, []


def normalized_mcp_server(server: Mapping[str, Any], transport: str) -> Dict[str, Any]:
    """Expose only the selected variant through the shared MCP role."""
    server = _normalized_structs(server)
    fields = _STDIO_FIELDS if transport == "stdio" else _HTTP_FIELDS
    result = {key: value for key, value in server.items() if key in fields}
    result["type"] = transport
    if transport != "stdio":
        result["url"] = next(server[key] for key in URL_FIELDS if key in server)
    for source, target in (
        ("oauth", "oauth"),
        ("startup_timeout_sec", "startupTimeout"),
        ("tool_timeout_sec", "timeout"),
    ):
        if source in server:
            result[target] = server[source]
    return result
