"""Pi's authored resource contract (upstream v1.0.0, 2026-10-01; MCP, settings
schema and changelogPath v1.5.0, 2026-11-02).

See https://pi.dev/docs/latest/packages and packages/coding-agent/src/core/{pi-manifest,
package-manager,skills}.ts in https://github.com/earendil-works/pi.
"""

import json
from functools import lru_cache
from importlib import resources

RESOURCE_FIELDS = ("extensions", "skills", "prompts", "themes")
TOOL_DIR_NAME = ".pi"
REMOTE_PREFIXES = ("npm:", "git:", "https://", "http://", "ssh://", "git://")
# Top-level settings keys whose shape pi-config-valid owns.
SETTINGS_RESOURCE_KEYS = (*RESOURCE_FIELDS, "packages")
SETTINGS_SCHEMA_VERSION = "1.5.0"

# Pi 1.5.0, packages/coding-agent/src/core/mcp-servers.ts.
MCP_EXPOSURES = frozenset({"codemode", "deferred", "direct", "hidden", "codemode-deferred"})
MCP_HTTP_TYPES = frozenset({"http", "streamable-http"})
MCP_OAUTH_STRING_FIELDS = (
    "clientId",
    "clientSecret",
    "scope",
    "callbackUrl",
    "clientName",
    "authServerMetadataUrl",
)
MCP_CLIENT_REGISTRATIONS = frozenset({"auto", "dcr", "cimd"})
# Pi 1.5.0, packages/coding-agent/src/extensions/mcp/config.ts: a project entry
# with none of the definition keys overrides the global server of that name.
MCP_DEFINITION_KEYS = ("command", "url", "type")
MCP_OVERRIDE_KEYS = ("enabled", "exposure", "toolExposure")
# ECMAScript String.trim removes BOM but not NEL or ASCII file separators.
JS_TRIM_CHARS = (
    "\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005"
    "\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
)


def string_list(value: object) -> bool:
    """Pi accepts an entire resource field only when every item is a string."""
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def settings_resources(settings: dict) -> dict:
    """Apply Pi's legacy skills migration without mutating cached settings.

    settings-manager.ts migrates only the top-level settings object; package
    manifests and package selectors retain the array-only resource contract.
    """
    skills = settings.get("skills")
    if not isinstance(skills, dict):
        return settings
    effective = settings.copy()
    directories = skills.get("customDirectories")
    if isinstance(directories, list) and directories:
        effective["skills"] = directories
    else:
        effective.pop("skills")
    return effective


@lru_cache(maxsize=1)
def settings_schema() -> dict:
    """The bundled Pi settings schema; linting never fetches pi.dev."""
    resource = resources.files("skillsaw.schemas.pi.v1_5_0").joinpath("settings.schema.json")
    with resource.open("r", encoding="utf-8") as stream:
        return json.load(stream)
