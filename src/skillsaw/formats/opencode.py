"""OpenCode configuration vocabulary, in one place.

OpenCode 2.0 renames a large part of its configuration while continuing to
load the 1.x spelling: a v1 key is normalized in memory rather than
rejected. Every check that reads an OpenCode config therefore has to accept
both, and this module is the single mapping that says which spellings are a
pair. When 2.0 reaches GA and the v1 names are finally dropped, tightening
skillsaw is an edit to this file rather than a hunt through rule code.

Sources: https://opencode.ai/docs/config/ (v1),
https://opencode.ai/v2/docs/config (v2) and
https://opencode.ai/v2/docs/migrate-v1 (the rename table), read against the
published JSON Schema at https://opencode.ai/config.json.
"""

from __future__ import annotations

from typing import Any, Mapping, Tuple

#: The value OpenCode documents for ``$schema``. Both versions point at the
#: same URL — there is no ``/v2/config.json`` — so a config that names it is
#: correct whichever release reads it.
SCHEMA_URL = "https://opencode.ai/config.json"

#: The separate schema for ``tui.json``, named here so a config that points
#: ``opencode.json`` at it gets a diagnostic that says which file it belongs
#: to rather than a bare "unrecognized".
TUI_SCHEMA_URL = "https://opencode.ai/tui.json"

#: Top-level v1 key -> its v2 spelling. Only genuine renames appear here; a
#: key spelled the same in both versions is in :data:`SHARED_TOP_LEVEL_KEYS`.
#:
#: ``mode`` and ``tools`` are *merges* rather than one-to-one renames —
#: v1 ``mode`` entries become primary agents under ``agents``, and v1
#: ``tools`` folds into the v2 ``permissions`` array — but the v1 key is
#: still accepted, which is all this table is consulted for.
TOP_LEVEL_V1_TO_V2: Mapping[str, str] = {
    "agent": "agents",
    "mode": "agents",
    "command": "commands",
    "permission": "permissions",
    "provider": "providers",
    "plugin": "plugins",
    "snapshot": "snapshots",
    "attachment": "media",
    "reference": "references",
    "autoshare": "share",
    "tools": "permissions",
}

#: Top-level keys spelled identically in v1 and v2, from the v1 JSON Schema
#: (which declares ``additionalProperties: false``) plus the keys v2 adds.
SHARED_TOP_LEVEL_KEYS: Tuple[str, ...] = (
    "$schema",
    "autoupdate",
    "compaction",
    "default_agent",
    "disabled_providers",
    "enabled_providers",
    "enterprise",
    "experimental",
    "formatter",
    "instructions",
    "layout",
    "logLevel",
    "lsp",
    "mcp",
    "model",
    "server",
    "share",
    "shell",
    "skills",
    "small_model",
    "subagent_depth",
    "tool_output",
    "username",
    "watcher",
    # v2 only: session warming.
    "warming",
    # Deprecated in v1 and migrated automatically when OpenCode can, so
    # they are still written in the wild and are not worth a diagnostic of
    # their own. Their home is ``tui.json``.
    "theme",
    "keybinds",
    "tui",
)

#: Every top-level key either version accepts. The union is deliberate: a
#: rule that knew only one release's vocabulary would report a correct
#: config as wrong the day the project upgraded, or the day it did not.
TOP_LEVEL_KEYS = frozenset(
    (*SHARED_TOP_LEVEL_KEYS, *TOP_LEVEL_V1_TO_V2, *TOP_LEVEL_V1_TO_V2.values())
)

#: Agent-entry key -> its v2 spelling, for entries under ``agent``/``agents``
#: (in the config and in ``.opencode/agents/*.md`` frontmatter alike).
AGENT_V1_TO_V2: Mapping[str, str] = {
    "prompt": "system",
    "disable": "disabled",
    "permission": "permissions",
    "maxSteps": "steps",
}

#: Agent-entry keys spelled the same in both versions.
SHARED_AGENT_KEYS: Tuple[str, ...] = (
    "description",
    "model",
    "variant",
    "temperature",
    "top_p",
    "tools",
    "mode",
    "hidden",
    "options",
    "color",
    "request",
)

#: Every agent-entry key either version accepts.
AGENT_KEYS = frozenset((*SHARED_AGENT_KEYS, *AGENT_V1_TO_V2, *AGENT_V1_TO_V2.values()))

#: Command-entry keys. Unchanged between versions.
COMMAND_KEYS = frozenset({"template", "description", "agent", "model", "variant", "subtask"})

#: MCP server key -> its v2 spelling. ``enabled`` is not a plain rename: v2
#: spells it ``disabled`` with the sense inverted, so a server carrying both
#: says two different things at once rather than the same thing twice.
MCP_SERVER_V1_TO_V2: Mapping[str, str] = {
    "enabled": "disabled",
}

#: Renamed keys inside an MCP server's ``oauth`` object, which v2 snake-cases.
MCP_OAUTH_V1_TO_V2: Mapping[str, str] = {
    "clientId": "client_id",
    "clientSecret": "client_secret",
    "callbackPort": "callback_port",
    "redirectUri": "redirect_uri",
}

#: Pairs whose two spellings do not merely differ but disagree, mapped to the
#: clause that says so in a diagnostic.
INVERTED_SENSE_NOTE: Mapping[str, str] = {
    "enabled": " with the sense inverted",
}

#: Transport values OpenCode accepts, mapped to the connection field each
#: one requires. OpenCode names a transport for where the server runs rather
#: than for the wire protocol, which is why the Claude-family shape check
#: cannot read these files.
MCP_SERVER_TYPES: Mapping[str, str] = {
    "local": "command",
    "remote": "url",
}

#: Keys an MCP server entry may carry, in either version. ``timeout`` is a
#: number in v1 and an object with ``catalog``/``execution`` in v2; both are
#: accepted, so the key appears once.
MCP_SERVER_KEYS = frozenset(
    {
        "type",
        "command",
        "cwd",
        "environment",
        "url",
        "headers",
        "oauth",
        "timeout",
        "enabled",
        "disabled",
    }
)


def timeout_is_valid(value: Any) -> bool:
    """Whether an MCP ``timeout`` is one of the two shapes OpenCode reads.

    v1 takes a number of milliseconds. v2 takes an object splitting the
    budget into ``catalog`` (listing the server's tools) and ``execution``
    (running one). Both are accepted; a bool is neither, however
    permissively you read it.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if not isinstance(value, dict):
        return False
    if not set(value) <= {"catalog", "execution"}:
        return False
    return all(
        isinstance(part, (int, float)) and not isinstance(part, bool) for part in value.values()
    )


def unknown_keys(data: Mapping[str, Any], known: frozenset) -> Tuple[str, ...]:
    """String keys of *data* that are not in *known*, in document order.

    Non-string keys cannot occur in parsed JSON, but a caller may pass a
    mapping built elsewhere; they are skipped rather than stringified.
    """
    return tuple(key for key in data if isinstance(key, str) and key not in known)


def both_spellings(data: Mapping[str, Any], aliases: Mapping[str, str]) -> Tuple[str, ...]:
    """v1 keys of *data* whose v2 spelling is declared beside them.

    Nothing branches on the answer, because either spelling on its own is
    valid. Carrying both is the finding: OpenCode 2.0 normalizes the v1 key
    into the v2 one, so the same setting arrives twice and which copy
    survives depends on merge order.

    Aliases that map several v1 keys onto one v2 key (``agent`` and ``mode``
    both become ``agents``) are handled by the plain membership test — each
    v1 key is reported against the v2 key it becomes.
    """
    return tuple(
        key for key in data if key in aliases and aliases[key] != key and aliases[key] in data
    )
