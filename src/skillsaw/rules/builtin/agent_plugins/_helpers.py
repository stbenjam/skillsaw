"""Shared helpers for versioned Agent Plugins validation."""

from __future__ import annotations

import hashlib

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from skillsaw.context import RepositoryType
from skillsaw.diagnostics import safe_display
from skillsaw.formats.agent_plugins import (
    SUPPORTED_AGENT_PLUGIN_SCHEMA_VERSIONS,
    load_agent_plugin_schema,
)
from skillsaw.rules.builtin.utils import (  # noqa: F401  — re-exported for rule modules
    strict_json,
)

AGENT_PLUGIN_REPO_TYPES = {RepositoryType.AGENT_PLUGIN}

PLUGIN_SCHEMAS = {
    version: load_agent_plugin_schema("plugin.schema.json", version)
    for version in SUPPORTED_AGENT_PLUGIN_SCHEMA_VERSIONS
}
MCP_SCHEMAS = {
    version: load_agent_plugin_schema("mcp.schema.json", version)
    for version in SUPPORTED_AGENT_PLUGIN_SCHEMA_VERSIONS
}
PLUGIN_VALIDATORS = {
    version: Draft202012Validator(schema) for version, schema in PLUGIN_SCHEMAS.items()
}
MCP_VALIDATORS = {version: Draft202012Validator(schema) for version, schema in MCP_SCHEMAS.items()}

# The portable fields are currently identical across supported schema versions.
MANIFEST_FIELDS = frozenset().union(*(schema["properties"] for schema in PLUGIN_SCHEMAS.values()))


def format_schema_error(error: ValidationError) -> str:
    """Render a compact schema failure without echoing the invalid value."""
    path = "$"
    for part in error.absolute_path:
        path += f"[{part}]" if isinstance(part, int) else f".{safe_display(part)}"
    if error.validator == "type":
        detail = f"must be of type {safe_display(error.validator_value)}"
    elif error.validator == "const":
        detail = f"must equal {safe_display(error.validator_value)!r}"
    elif error.validator == "pattern":
        detail = "does not match the required pattern"
    elif error.validator == "minLength":
        detail = f"must contain at least {error.validator_value} character(s)"
    elif error.validator == "maxLength":
        detail = f"must contain at most {error.validator_value} character(s)"
    elif error.validator == "oneOf":
        detail = "must match exactly one permitted schema variant"
    elif error.validator == "not":
        # propertyNames applies the schema to the key itself. Keys are useful
        # locators, unlike values (which may contain credentials).
        detail = f"prohibited name {safe_display(error.instance)!r}"
    elif error.validator in {"required", "additionalProperties"}:
        # These jsonschema messages contain property names, never values.
        detail = safe_display(error.message)
    else:
        detail = f"violates the {safe_display(error.validator)!r} constraint"
    return f"{path}: {detail}"


def stable_key(value: object) -> str:
    """Short stable identifier for an untrusted diagnostic discriminator."""
    return hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()[:16]


def schema_error_summary(errors: list[ValidationError], *, limit: int = 4) -> str:
    """Summarize schema errors without flooding one malformed document."""
    ordered = sorted(
        errors, key=lambda error: (tuple(map(str, error.absolute_path)), error.message)
    )
    rendered = [format_schema_error(error) for error in ordered[:limit]]
    remaining = len(ordered) - len(rendered)
    if remaining:
        rendered.append(f"and {remaining} more schema error{'s' if remaining != 1 else ''}")
    return "; ".join(rendered)
