"""Skillsaw-authored validation of Cursor's documented packaging fields.

Reference: https://cursor.com/docs/reference/plugins (2026-09-18).
This is an interoperability schema, not Cursor's publication policy. Metadata
extensions and npm-style author/repository values occur in working packages;
unknown fields and URL/email spellings are deliberately not rejected.
No upstream schema or description text is redistributed here.
"""

from functools import lru_cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jsonschema import Draft7Validator


@lru_cache(maxsize=2)
def validator(kind: str) -> "Draft7Validator":
    # jsonschema costs ~19ms to import; rule discovery imports this module
    # on every run, and only a Cursor package ever validates against it.
    from jsonschema import Draft7Validator

    text = {"type": "string"}
    strings = {"type": "array", "items": text}
    paths = {"anyOf": [text, strings]}
    person = {
        "anyOf": [
            text,
            {
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string", "minLength": 1}, "email": text},
            },
        ]
    }
    config = {"anyOf": [text, {"type": "object"}]}
    properties = {
        key: text
        for key in (
            "displayName",
            "description",
            "version",
            "publisher",
            "homepage",
            "license",
            "logo",
            "category",
        )
    }
    properties.update(
        {
            "name": {
                "type": "string",
                "minLength": 1,
                "pattern": "^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$",
            },
            "author": person,
            "repository": config,
            "keywords": strings,
            "tags": strings,
            "minClientVersions": {"type": "object", "additionalProperties": text},
            **{key: paths for key in ("commands", "rules", "agents", "skills")},
            "hooks": config,
            "mcpServers": {"anyOf": [*config["anyOf"], {"type": "array", "items": config}]},
            "variables": {
                "type": "object",
                "required": ["type"],
                "properties": {
                    "type": {"const": "object"},
                    "properties": {"type": "object"},
                    "required": {**strings, "uniqueItems": True},
                },
            },
        }
    )
    schema = {"type": "object", "required": ["name"], "properties": properties}
    if kind == "marketplace":
        source = {
            "anyOf": [
                {"type": "string", "minLength": 1},
                {
                    "type": "object",
                    "required": ["path"],
                    "properties": {"path": {"type": "string", "minLength": 1}},
                },
            ]
        }
        entry = {
            "type": "object",
            "required": ["name", "source"],
            "properties": {**properties, "source": source},
        }
        schema = {
            "type": "object",
            "required": ["name", "plugins"],
            "properties": {
                "name": {"type": "string", "minLength": 1},
                "owner": person,
                "metadata": {
                    "type": "object",
                    "properties": {key: text for key in ("description", "pluginRoot", "version")},
                },
                "plugins": {"type": "array", "items": entry},
            },
        }
    elif kind != "plugin":
        raise ValueError(f"Unknown Cursor schema: {kind}")
    return Draft7Validator(schema)
