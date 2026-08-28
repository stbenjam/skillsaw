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

**Re-check at each OpenCode 2.0 milestone** (last verified 2026-08-28
against ``anomalyco/opencode@dev``, the only branch — there is no ``main``).
Two independent, opposite-direction code paths define the vocabulary, and
they disagree with each other today:

* ``packages/opencode/src/config/v2-compat.ts`` — what a **1.x** binary uses
  to lower a v2-shaped config *down* into v1. Holds the server structs and
  ``preferLegacy()``, which retains the legacy value for every key.
* ``packages/core/src/v1/config/migrate.ts`` plus
  ``packages/core/src/config.ts`` — what **2.0** uses to migrate a v1 config
  *up*. Holds ``isV1()`` and the per-key coalescing that
  :data:`V2_WINS_UNDER_V2` records.

Their MCP timeout structs differ, which is why :data:`MCP_TIMEOUT_KEYS` is a
union rather than either one.

There is no published v2 JSON Schema; ``/v2/config.json`` 404s and the v2
docs still advertise the v1 URL. Until 2.0 is GA, keep every v2-only *value*
constraint here as permissive as the union of those files: accepting a shape
that later proves wrong costs nothing, while rejecting a correct one is a
false positive in someone's CI.
"""

from __future__ import annotations

from typing import Any, FrozenSet, Mapping, Tuple

#: The value OpenCode documents for ``$schema``. Both versions point at the
#: same URL — there is no ``/v2/config.json`` — so a config that names it is
#: correct whichever release reads it.
SCHEMA_URL = "https://opencode.ai/config.json"

#: The separate schema for ``tui.json``, named here so a config that points
#: ``opencode.json`` at it gets a diagnostic that says which file it belongs
#: to rather than a bare "unrecognized".
TUI_SCHEMA_URL = "https://opencode.ai/tui.json"

#: Top-level v1 key -> its v2 spelling, for one-to-one *renames* only. A key
#: spelled the same in both versions is in :data:`SHARED_TOP_LEVEL_KEYS`.
#:
#: Only renames belong here, because this table also drives the
#: "declares both spellings" diagnostic: for a rename, the two keys are the
#: same setting written twice and one of them is inert. That claim is false
#: for a merge, so merges live in :data:`TOP_LEVEL_MERGED_INTO` instead.
TOP_LEVEL_V1_TO_V2: Mapping[str, str] = {
    "agent": "agents",
    "command": "commands",
    "permission": "permissions",
    "provider": "providers",
    "plugin": "plugins",
    "snapshot": "snapshots",
    "attachment": "media",
    "reference": "references",
    "autoshare": "share",
}

#: v1 key -> the v2 key it folds *into*, rather than is renamed to. v1
#: ``mode`` entries become primary agents under ``agents``, and v1 ``tools``
#: folds into the v2 ``permissions`` array.
#:
#: Deliberately outside :data:`TOP_LEVEL_V1_TO_V2`: a config declaring both
#: halves of a merge is doing something supported, not something ambiguous,
#: so telling the author one of them is inert — and to delete a section that
#: is loading correctly — would be wrong. Both keys are still accepted,
#: which is what :data:`TOP_LEVEL_KEYS` unions them in for.
TOP_LEVEL_MERGED_INTO: Mapping[str, str] = {
    "mode": "agents",
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
    # ``attachments`` and ``media`` are the same setting under two names
    # that ship at once: ``packages/core/src/config.ts`` declares
    # ``attachments`` and the v1 migration emits it, while the docs and
    # ``v2-compat.ts`` say ``media``. Same two-disagreeing-declarations case
    # as ``MCP_TIMEOUT_KEYS``, resolved the same way — accept both.
    "attachments",
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
    # v2 only. ``v2-compat.ts`` L117 lists both as top-level keys a 1.x
    # binary cannot lower; ``warming`` is also in ``Config.Info`` while
    # ``websearch`` appears there only as a permission action. Accepted on
    # the same permissive-union policy as ``attachments``.
    "warming",
    "websearch",
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
    (
        *SHARED_TOP_LEVEL_KEYS,
        *TOP_LEVEL_V1_TO_V2,
        *TOP_LEVEL_V1_TO_V2.values(),
        *TOP_LEVEL_MERGED_INTO,
        *TOP_LEVEL_MERGED_INTO.values(),
    )
)

#: Agent-entry key -> its v2 spelling, for entries under ``agent``/``agents``.
#:
#: There is deliberately no companion set of *known* agent keys: OpenCode
#: folds an unrecognized agent field into the provider ``options``, so naming
#: one is a supported way to pass a provider-specific setting and reporting
#: it would be a false positive.
AGENT_V1_TO_V2: Mapping[str, str] = {
    "prompt": "system",
    "disable": "disabled",
    "permission": "permissions",
    "maxSteps": "steps",
}

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

#: Pairs whose two spellings contradict each other rather than duplicate,
#: mapped to the clause that says so in a diagnostic.
INVERTED_SENSE_NOTE: Mapping[str, str] = {
    "enabled": " with the sense inverted",
}

#: v1 keys whose *v2* spelling wins when a config declares both — and only
#: under OpenCode 2.0, which is why they are called out separately.
#:
#: The rule is structural rather than arbitrary. ``ConfigV1.Info`` declares
#: both halves of these two pairs (each marked deprecated), so the v1→v2
#: migration can coalesce them and does: ``v1/config/migrate.ts`` reads
#: ``share: info.share ?? (info.autoshare ? "auto" : undefined)`` and
#: ``references: info.references ?? info.reference``. Every other pair
#: renames to a name the v1 schema does not know, so the presence of the v1
#: key makes ``isV1()`` claim the whole document, the v2 key is dropped as an
#: excess property, and the v1 value stands.
#:
#: A 1.x binary disagrees for exactly these two: ``v2-compat.ts`` lowers a v2
#: config into v1 shape and its ``preferLegacy()`` retains the legacy value
#: for every key. So for these pairs the effective value depends on which
#: release reads the file, which is worth saying out loud in a diagnostic.
V2_WINS_UNDER_V2: FrozenSet[str] = frozenset({"autoshare", "reference"})

#: Transport values OpenCode accepts, mapped to the connection field each
#: one requires. OpenCode names a transport for where the server runs rather
#: than for the wire protocol, which is why the Claude-family shape check
#: cannot read these files.
MCP_SERVER_TYPES: Mapping[str, str] = {
    "local": "command",
    "remote": "url",
}

#: Keys an MCP server entry may carry, in either version. ``timeout`` is a
#: number in v1 and an object in v2; both are accepted, so the key appears
#: once. ``cwd``/``environment`` are local-only and ``url``/``headers``/
#: ``oauth`` remote-only upstream; they are pooled here because the
#: per-transport split is enforced by :data:`MCP_SERVER_TYPES` and a
#: cross-transport key is a wrong-place warning, not an unknown key.
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
        # v2 only: route this server's tools through Code Mode. Declared on
        # both the local and the remote struct in ``v2-compat.ts``.
        "codemode",
        # Not a v2 field at all — v2 spells it ``disabled``. The compat shim
        # reads it as a legacy v1 spelling and passes it through, so a config
        # carrying it still works and skillsaw accepts it.
        "enabled",
        "disabled",
    }
)

#: Sub-keys a v2 ``timeout`` object may carry. Deliberately the *union* of
#: two upstream declarations that disagree: ``v2-compat.ts`` declares
#: ``{startup, catalog, execution}`` while ``packages/core/src/config/mcp.ts``
#: declares ``{startup, request}``. Both ship today, and OpenCode's own v2 MCP
#: documentation uses the first — so rejecting either set would report a
#: correctly written config as wrong, which is the one thing this module
#: exists to prevent.
MCP_TIMEOUT_KEYS = frozenset({"startup", "catalog", "execution", "request"})


def timeout_is_valid(value: Any) -> bool:
    """Whether an MCP ``timeout`` is one of the two shapes OpenCode reads.

    v1 takes a number of milliseconds. v2 takes an object splitting the
    budget across :data:`MCP_TIMEOUT_KEYS`, also in milliseconds. Both are
    accepted; a bool is neither, though ``isinstance(True, int)`` holds.
    """
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if not isinstance(value, dict):
        return False
    if not set(value) <= MCP_TIMEOUT_KEYS:
        return False
    return all(
        isinstance(part, (int, float)) and not isinstance(part, bool) for part in value.values()
    )


def unknown_keys(data: Mapping[str, Any], known: FrozenSet[str]) -> Tuple[str, ...]:
    """String keys of *data* that are not in *known*, in document order.

    Non-string keys cannot occur in parsed JSON, but a caller may pass a
    mapping built elsewhere; they are skipped rather than stringified.
    """
    return tuple(key for key in data if isinstance(key, str) and key not in known)


def both_spellings(data: Mapping[str, Any], aliases: Mapping[str, str]) -> Tuple[str, ...]:
    """v1 keys of *data* whose v2 spelling is declared beside them.

    No caller treats a lone v1 key as wrong — either spelling on its own is
    valid. Carrying both is the finding: one of the two is then ignored, and
    which one is not something an author can read off the file. It is not
    key order, and it is not arbitrary either — see
    :data:`V2_WINS_UNDER_V2` for the two pairs where the answer inverts, and
    where the two OpenCode releases disagree with each other.

    Aliases that map several v1 keys onto one v2 key (``agent`` and ``mode``
    both become ``agents``) are handled by the plain membership test — each
    v1 key is reported against the v2 key it becomes.
    """
    return tuple(
        key for key in data if key in aliases and aliases[key] != key and aliases[key] in data
    )
