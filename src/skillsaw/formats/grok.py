r"""Grok Build repository-context vocabulary, in one place.

Grok Build is xAI's terminal coding agent. A checkout configures it through
``.grok/``: portable Agent Skills in ``skills/``, always-on prose in
``rules/``, slash commands in ``commands/``, subagents in ``agents/``, and
lifecycle hooks in ``hooks/*.json``. MCP servers are *not* configured here
— see :data:`CONFIG_FILENAME`. Two of those surfaces have a shape no other
rule already validates, the hooks files and the subagents, so the
Grok-specific facts live here rather than spread through rule code.

Sources:

* The user guide shipped with 1.0.13 — ``10-hooks.md`` (events, the Cursor
  alias table, handler fields, the reserved environment variables, the
  matcher-per-event table), ``12-project-rules.md``, ``08-skills.md``,
  ``04-slash-commands.md``, ``16-subagents.md``, ``26-config-reference.md``.
* Strings read from the shipped executable, whose hook loader is
  ``crates/codegen/xai-grok-hooks/src/config.rs``. Its diagnostics name the
  handler contract directly: ``command handler requires a 'command' field``,
  ``http handler requires a 'url' field``, ``hooks: skipped unrecognized
  event names (check for typos).`` and ``hook env: ignoring user-supplied
  value for runner-reserved key (the runner-injected value always wins)``.

Everything below was verified against Grok Build 1.0.13 (``5e9a58528b76``,
stable) rather than read off the docs. Method: an isolated ``GROK_HOME``
(the real ``~/.grok`` untouched) with one hook file per case under
``$GROK_HOME/hooks/`` — user scope, always trusted, so no folder-trust gate
— each handler carrying a unique ``command`` token, read back from ``grok
inspect --json``. Every case carries a canary handler in the same group and
a canary group under a different event in the same file, so file scope,
group scope and handler scope are told apart rather than assumed. Re-run
that matrix before changing a rule here.

The file is the nested shape Claude Code defined: ``{"hooks": {Event:
[{matcher?, hooks: [handler, ...]}, ...]}}``. Grok reads
``<project>/.grok/hooks/*.json`` as a flat glob — a nested directory and a
non-``.json`` extension are both ignored — and merges every file it finds.
Failure scope then differs by level, and the scope is what makes a defect
worth reporting, because ``grok inspect --json`` reported
``configWarnings: null`` for every failing case: the runtime tells the
author nothing.

* **Whole file** — a UTF-8 byte-order mark at the start of the file, which
  ``serde_json`` refuses and Python's ``utf-8-sig`` decoding hides (verified:
  ``grok inspect --json`` loaded zero hooks from an otherwise-correct file
  with a leading BOM); malformed JSON; a bare ``NaN``, ``Infinity`` or
  ``-Infinity`` token, which Python's ``json`` accepts as a float and
  ``serde_json`` refuses; no top-level ``hooks`` object; an event whose
  value is not an array; a matcher group that is not an object; a group
  with no ``hooks`` key or a non-array one; a ``matcher`` that is not a
  string, which never reaches the regex compiler; a handler that is not an
  object; a handler with no ``type``, or a ``null`` one; and any field in
  :data:`HANDLER_FIELDS` carrying the wrong JSON type, including a
  ``timeout`` above :data:`TIMEOUT_MAX`. A ``null`` is not one of those
  wrong types — Grok reads it as the key being absent, so it costs whatever
  omitting the key costs, and ``type`` is the only field whose ``null``
  reaches this bullet. One mistyped ``timeout`` costs the author every hook
  in the file.
* **That matcher group** — a ``matcher`` string that does not compile.
* **That event's entries** — an event name outside :data:`HOOK_EVENTS` and
  :data:`HOOK_EVENT_ALIASES`. The rest of the file loads.
* **That handler** — a ``command`` handler with no ``command`` or a ``null``
  one, an ``http`` handler with no ``url`` or a ``null`` one, or a ``type``
  outside :data:`HOOK_HANDLER_TYPES`. Sibling handlers still run.
* **Tolerated** — an unknown key on a handler, on a matcher group
  (``description``), or at the top level; an empty ``hooks`` array; an
  empty ``matcher``; a ``null`` ``timeout``, ``env`` or ``matcher``, and a
  ``null`` in any other field the handler's type does not require.

``matcher`` is a regex Grok compiles at load time with Rust's ``regex``
crate — verified by loading ``\p{L}+`` and ``[a-z&&[^aeiou]]``, which
Python's ``re`` rejects, and by watching ``(?<=x)y`` and ``(a)\1`` drop
their groups, which Rust rejects and Python accepts. ``""`` and ``"*"`` are
both catch-alls rather than patterns. What the matcher tests depends on the
event; on the two events in :data:`MATCHER_IGNORED_EVENTS` it is kept in
the configuration and ignored at dispatch.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Set

# ``inline_documents`` unpacks the "a path, an array of paths, or the object
# itself" manifest shape Claude Code defined and both Codex and Grok
# inherited. It lives beside the reader that needed it first rather than
# being copied here, so one fix covers both ecosystems.
from skillsaw.formats.codex import inline_documents
from skillsaw.formats.grok_mcp import decode_mcp_server
from skillsaw.paths import (
    contained_resolve,
    safe_exists,
    safe_is_dir,
    safe_is_file,
    safe_is_symlink,
    safe_resolve,
)
from skillsaw.utils import read_json

#: The project directory Grok Build reads. Grok loads the ``.grok/`` layer
#: of the project it is started in, which in a monorepo is as often a
#: package as the repository root.
TOOL_DIR_NAME = ".grok"

#: Lifecycle hooks, relative to :data:`TOOL_DIR_NAME`: a directory of
#: ``*.json`` files read as a flat glob, not one file. Project hooks are
#: folder-trust gated; the skills, rules, commands and agents beside them
#: are not.
HOOKS_DIR_NAME = "hooks"

#: The glob Grok reads inside :data:`HOOKS_DIR_NAME`. Flat: a hooks file in
#: a subdirectory is never loaded.
HOOKS_GLOB = "*.json"

#: Directories of authored prose under :data:`TOOL_DIR_NAME`, each read
#: **flat** — a nested ``rules/theme/style.md`` is not loaded, so an
#: attachment glob for these must not recurse. ``skills/`` is the exception
#: and is walked recursively; it is discovered through
#: ``CONVENTIONAL_SKILL_DIRS`` instead, which earns the whole skill rule set.
RULES_DIR_NAME = "rules"
COMMANDS_DIR_NAME = "commands"
AGENTS_DIR_NAME = "agents"
SKILLS_DIR_NAME = "skills"

#: Project configuration, parsed as TOML and attached — see
#: :data:`PROJECT_CONFIG_TABLES` for the four tables that survive project
#: scope. LSP servers are not parsed; file existence alone is what makes
#: that one evidence.
#:
#: There is deliberately no ``.grok/mcp.json`` here. Grok's MCP sources are
#: ``config.toml`` ``[mcp_servers]``, ``~/.claude.json``,
#: ``.cursor/mcp.json`` and the repository-root ``.mcp.json`` — skillsaw
#: already attaches the last of those — and a ``.grok/mcp.json`` placed in a
#: trusted project loaded nothing when verified against the binary. Attaching
#: it would lint a file Grok never reads.
CONFIG_FILENAME = "config.toml"
LSP_FILENAME = "lsp.json"

#: The rest of the project layer, on the same footing as
#: :data:`LSP_FILENAME`: Grok configuration nothing here parses or
#: attaches, listed because *existence* is what makes a directory Grok's.
#: A repository whose only Grok artifact is a sandbox policy is a Grok
#: repository, and the summary saying ``unknown`` would be wrong about it.
#: Adding one costs a line here and in ``_TOOL_EVIDENCE``, and nothing
#: else — detection and attachment stay in agreement because neither
#: attaches anything for these.
WORKFLOWS_DIR_NAME = "workflows"
ROLES_DIR_NAME = "roles"
PERSONAS_DIR_NAME = "personas"
SANDBOX_FILENAME = "sandbox.toml"

#: Project-scoped plugins, relative to :data:`TOOL_DIR_NAME`. An install
#: location rather than authored configuration: Grok's own plugin discovery
#: owns it, so the project attach loop steps over it.
PLUGINS_DIR_NAME = "plugins"

#: The 15 lifecycle events Grok dispatches. A hook binds to exactly one; an
#: unknown name loses that event's entries and nothing else, and the loader
#: says so only in a debug log ("hooks: skipped unrecognized event names").
HOOK_EVENTS = frozenset(
    {
        "SessionStart",
        "SessionEnd",
        "UserPromptSubmit",
        "PreToolUse",
        "PostToolUse",
        "PostToolUseFailure",
        "PermissionDenied",
        "Stop",
        "StopFailure",
        "StopCancelled",
        "Notification",
        "SubagentStart",
        "SubagentStop",
        "PreCompact",
        "PostCompact",
    }
)

#: Every other spelling Grok's deserializer accepts, mapped to the event it
#: normalises to. Three families, and the point of the table is that
#: accepting all of them is a correctness requirement: a missing entry turns
#: a working hooks file into a false "unknown event".
#:
#: * ``snake_case`` for all 16 names: the 15 events in :data:`HOOK_EVENTS`
#:   plus ``subagent_end``, which is not a sixteenth event but the
#:   snake_case spelling of the ``SubagentEnd`` alias below. This is the
#:   wire spelling Grok also uses in ``GROK_HOOK_EVENT`` and in the hook's
#:   stdin envelope.
#: * ``camelCase``, which covers every event **except**
#:   ``userPromptSubmit`` — that one spelling is not accepted, verified
#:   alongside the thirteen that are.
#: * Cursor's per-operation names, so a ``~/.cursor/hooks.json`` loads
#:   unchanged. Each maps to the generic tool event and the script filters
#:   on the tool name in its input.
#:
#: ``SubagentEnd`` and its two other spellings are Grok's own documented
#: alias for ``SubagentStop``.
HOOK_EVENT_ALIASES: Mapping[str, str] = {
    # snake_case
    "session_start": "SessionStart",
    "session_end": "SessionEnd",
    "user_prompt_submit": "UserPromptSubmit",
    "pre_tool_use": "PreToolUse",
    "post_tool_use": "PostToolUse",
    "post_tool_use_failure": "PostToolUseFailure",
    "permission_denied": "PermissionDenied",
    "stop": "Stop",
    "stop_failure": "StopFailure",
    "stop_cancelled": "StopCancelled",
    "notification": "Notification",
    "subagent_start": "SubagentStart",
    "subagent_stop": "SubagentStop",
    "subagent_end": "SubagentStop",
    "pre_compact": "PreCompact",
    "post_compact": "PostCompact",
    # camelCase
    "sessionStart": "SessionStart",
    "sessionEnd": "SessionEnd",
    "preToolUse": "PreToolUse",
    "postToolUse": "PostToolUse",
    "postToolUseFailure": "PostToolUseFailure",
    "permissionDenied": "PermissionDenied",
    "stopFailure": "StopFailure",
    "stopCancelled": "StopCancelled",
    "subagentStart": "SubagentStart",
    "subagentStop": "SubagentStop",
    "subagentEnd": "SubagentStop",
    "preCompact": "PreCompact",
    "postCompact": "PostCompact",
    # Grok's own documented alias
    "SubagentEnd": "SubagentStop",
    # Cursor compatibility
    "beforeShellExecution": "PreToolUse",
    "beforeMCPExecution": "PreToolUse",
    "beforeReadFile": "PreToolUse",
    "afterShellExecution": "PostToolUse",
    "afterMCPExecution": "PostToolUse",
    "afterFileEdit": "PostToolUse",
    "afterAgentResponse": "PostToolUse",
    "afterAgentThought": "PostToolUse",
    "beforeSubmitPrompt": "UserPromptSubmit",
}

#: Handler types Grok runs: a shell command, or an HTTP endpoint the event
#: envelope is POSTed to. The value is case-sensitive — ``"Command"``
#: drops the handler.
HOOK_HANDLER_TYPES = frozenset({"command", "http"})

#: The field each handler type needs before it can do anything. Missing it
#: drops that handler and nothing else, which is what the loader's
#: "command handler requires a 'command' field" / "http handler requires a
#: 'url' field" diagnostics describe.
HOOK_REQUIRED_FIELDS: Mapping[str, str] = {
    "command": "command",
    "http": "url",
}

#: The JSON type Grok accepts for each handler field it knows. A wrong type
#: here refuses the whole document, so this table is the whole-file check;
#: which fields a type *needs* is :data:`HOOK_REQUIRED_FIELDS`. ``timeout``
#: is additionally a non-negative integer no larger than
#: :data:`TIMEOUT_MAX` — ``1.5``, ``-1``, ``true`` and ``"30"`` each cost
#: every hook in the file. A merely *large* one is fine and is not a defect
#: (``Stop`` and ``SubagentStop`` default to 600 seconds, because gates run
#: test suites). ``env`` is a map of strings; a non-string value refuses the
#: document too.
HANDLER_FIELDS: Mapping[str, Any] = {
    "type": str,
    "command": str,
    "url": str,
    "timeout": int,
    "env": dict,
}

#: The largest ``timeout`` Grok's deserializer accepts. The field is a Rust
#: ``u64``, and JSON has no integer width, so the boundary is exact and
#: sharp: ``18446744073709551615`` loads, ``18446744073709551616`` refuses
#: the whole file — both verified against Grok Build 1.0.13. A number that
#: wide is a generated or pasted value rather than a duration anyone meant,
#: which is the only way it reaches a hooks file at all.
TIMEOUT_MAX = 2**64 - 1

#: Environment variables the hook runner injects into every hook process. A
#: value declared for one of these in a handler's ``env`` is dropped at load
#: time — "the runner-injected value always wins" — so the handler runs with
#: Grok's value, not the author's.
RESERVED_ENV_VARS = frozenset(
    {
        "GROK_HOOK_EVENT",
        "GROK_HOOK_NAME",
        "GROK_SESSION_ID",
        "GROK_WORKSPACE_ROOT",
        "CLAUDE_PROJECT_DIR",
    }
)

#: Variables the plugin adapter injects on top of those, for a hook a
#: plugin ships. Recorded for completeness — a project hooks file is not
#: plugin-provided, so nothing checks these until plugin support lands.
PLUGIN_ENV_VARS = frozenset(
    {
        "GROK_PLUGIN_ROOT",
        "GROK_PLUGIN_DATA",
        "CLAUDE_PLUGIN_ROOT",
        "CLAUDE_PLUGIN_DATA",
    }
)

#: The two events that always fire, so a ``matcher`` on them selects
#: nothing. Grok keeps the value in the loaded configuration and ignores it
#: at dispatch. Every other event matches the matcher against a field of its
#: own — the tool name, the notification type, the subagent type, the start
#: source, the compaction trigger, the error class, the cancel reason.
MATCHER_IGNORED_EVENTS = frozenset({"Stop", "UserPromptSubmit"})

#: Matchers Grok treats as "everything" rather than compiling as a pattern.
#: ``"*"`` is not a valid Rust regex, and reporting it would be a false
#: positive on a spelling Grok accepts and Claude Code's own files use.
WILDCARD_MATCHERS = frozenset({"", "*"})


def normalize_event(event: str) -> str:
    """The event *event* dispatches as, following Grok's alias table."""
    return HOOK_EVENT_ALIASES.get(event, event)


# -- Project ``config.toml`` --------------------------------------------------
#
# ``config.toml`` is one file read at four layers, and the project layer is
# the narrow one. The shipped user guide says so twice — "Project
# ``.grok/config.toml``: only ``[mcp_servers]``, ``[plugins]``,
# ``[permission]``, and ``[mcp] max_output_bytes``"
# (``26-config-reference.md``, restated under ``## config.toml``).
#
# ``inspect`` exposes project MCP servers and permissions, but does not call
# the live session's project plugin resolver. Its missing plugin output is
# not evidence that project paths are ignored. The pinned resolver extends
# trusted project ``plugins.paths`` and project ``plugins.disabled``:
# xai-grok-shell/src/config/mod.rs, resolve_effective_plugins_config(),
# grok-build 72a61251fcffb464bcc687aeb5a998e5a98ec0c9.

#: The documented top-level tables a project config contributes. Unknown
#: keys inside these tables stay open; no project plugin-path refusal is
#: inferred from the more limited ``inspect`` consumer.
PROJECT_CONFIG_TABLES = frozenset({"mcp_servers", "permission", "plugins", "mcp"})

#: The tables directly observable in ``inspect``. Plugin project support
#: additionally follows the live resolver above; ``mcp.max_output_bytes``
#: remains documented but unmeasured.
PROJECT_CONFIG_TABLES_MEASURED = frozenset({"mcp_servers", "permission"})

#: Tables a project file was measured to *not* contribute, each with a
#: positive user-scope control so "nothing happened" is a refusal rather
#: than a mis-run. ``hooks`` is the sharp one: the honored path for a
#: project's hooks is ``.grok/hooks/*.json``, which loads.
PROJECT_CONFIG_TABLES_REFUSED = frozenset({"hooks", "skills", "sandbox"})

#: Every field Grok accepts inside ``[mcp_servers.<name>]``. Anything else
#: raises an ``mcpConfigProblems`` warning and the server still loads, so
#: this is the vocabulary a rule may check membership against, never a
#: reason to call a file broken.
#:
#: ``transport`` is deliberately absent; see
#: :data:`MCP_TYPE_MISSPELLED_FIELD`.
MCP_SERVER_FIELDS = frozenset(
    {
        "args",
        "bearer_token_env_var",
        "command",
        "cwd",
        "enabled",
        "env",
        "expose_image_base64",
        "headers",
        "oauth",
        "oauth_client_id",
        "oauth_client_secret_env_var",
        "oauth_scopes",
        "setup",
        "startup_timeout_sec",
        "tool_timeout_sec",
        "tool_timeouts",
        "type",
        "url",
        "urlTemplate",
        "url_template",
    }
)

#: The fields that carry each transport, in the portable spelling every
#: other MCP host uses — which is what lets a ``config.toml`` server read
#: through the same :class:`~skillsaw.blocks.json_config.McpConfigRole` an
#: ``.mcp.json`` server does. ``connection`` is the field the transport
#: cannot start without.
MCP_TRANSPORT_FIELDS: Mapping[str, Mapping[str, str]] = {
    "stdio": {"connection": "command", "arguments": "args", "environment": "env"},
    "http": {"connection": "url", "environment": "headers"},
    "sse": {"connection": "url", "environment": "headers"},
}

#: The ``type`` value that selects SSE over HTTP for a URL server. ``type``
#: is otherwise advisory: a bogus one beside a ``command`` loads as stdio
#: with no diagnostic.
MCP_SSE_TYPE = "sse"


def mcp_transport(server: Mapping[str, Any]) -> Optional[str]:
    """Derive the transport using Grok's complete, ordered variant decoder."""
    return decode_mcp_server(server)[0]


#: The ``[permission]`` keys that hold compact rule strings, and the verbose
#: table array beside them. Measured: ``rules`` is discarded **entirely**
#: whenever any of the three compact keys holds an array, in any order, with no
#: diagnostic — which is the defect worth reporting, since a file carrying
#: both loses every verbose rule it wrote.
#:
#: The two forms also fail at different scopes, measured. A non-string entry
#: in a list key costs that entry: ``allow = ["Bash(git *)", 42]`` loads the
#: string beside the integer. A non-table entry in ``rules`` costs the whole
#: array: two valid rules beside a bare integer loaded nothing. Both are
#: silent, and an unparseable rule *string* costs its entry alone.
PERMISSION_TABLE = "permission"
PERMISSION_LIST_KEYS = frozenset({"allow", "deny", "ask"})
PERMISSION_RULES_KEY = "rules"

#: ``defaultMode``, a ``.claude/settings.json`` key with no meaning in a
#: ``[permission]`` table. Ignored, and Grok says nothing about it.
PERMISSION_MISSPELLED_KEY = "defaultMode"

#: Spellings that load no server and say nothing about it. The first is an
#: array-of-tables under ``[mcp]``; the other two are the top-level table
#: name written the way another host spells it. Each is a plausible
#: misreading of ``[mcp_servers.<name>]`` and each is a silent, total loss
#: of the declaration.
MCP_SERVERS_MISSPELLING = ("mcp", "servers")
MCP_SERVERS_MISSPELLED_TABLES = frozenset({"mcp-servers", "mcpServers"})

#: ``transport``, the plausible misspelling of the ``type`` field inside a
#: server table — deliberately absent from :data:`MCP_SERVER_FIELDS`, because
#: it is not an alias: measured, it is reported unrecognized and ignored.
MCP_TYPE_MISSPELLED_FIELD = "transport"

#: ``[permissions]``, the plural, loads nothing — and the file drops out of
#: ``permissions.sources`` altogether, so nothing marks its absence.
PERMISSION_MISSPELLED_TABLE = "permissions"

# -- Plugins and the marketplace ----------------------------------------------
#
# A plugin is a directory holding any of ``skills/``, ``commands/``,
# ``agents/``, ``hooks/hooks.json``, ``.mcp.json`` and ``.lsp.json``, plus an
# optional manifest that renames those paths or adds metadata. A marketplace
# is a repository listing plugins in ``.grok-plugin/marketplace.json``, with
# an optional ``plugin-index.json`` catalog beside it.
#
# Sources: the user guide shipped with 1.0.13 (``09-plugins.md``); the
# official catalog tooling at ``xai-org/plugin-marketplace@66f42b6`` —
# ``scripts/plugin_catalog.py`` for component resolution and
# ``scripts/validate-catalog.py`` for the catalog contract; and the manifest
# precedence and name boundaries measured against the binary with ``grok
# plugin validate``.

#: The reserved directory Grok's own plugin and marketplace files live in.
#: ``.claude-plugin`` is a documented fallback Grok reads, and is
#: deliberately *not* Grok's marker: a directory carrying only that one is a
#: Claude plugin the Claude rules already own.
#:
#: What each defect in these files costs is measured per input in "What the
#: packaging loader costs" in ``docs/designs/grok-build.md``; the severities
#: in ``rules/builtin/grok/`` are read off that table.
PLUGIN_DIR_NAME = ".grok-plugin"

#: Filenames inside :data:`PLUGIN_DIR_NAME`. ``plugin.json`` describes one
#: plugin; ``marketplace.json`` is the catalog Grok reads; ``plugin-index.json``
#: is the optional display catalog beside it, whose ``sha`` values a
#: ``require_sha`` deployment installs from.
PLUGIN_MANIFEST = "plugin.json"
MARKETPLACE_FILENAME = "marketplace.json"
PLUGIN_INDEX_FILENAME = "plugin-index.json"

#: The file that makes a directory a skill rather than a folder of notes.
#: Named here because the structure rule, the parity rule and the override
#: check ask the same question of the same directories.
SKILL_FILENAME = "SKILL.md"

#: Where a marketplace's catalog may live, in the order Grok resolves them.
#: Exactly one is read, never merged — verified by building a repository
#: carrying two catalogs listing different plugins and reading back ``grok
#: plugin list --json --available``. The root spelling is *last* here and
#: *first* in :data:`MANIFEST_PATHS`; the two lookups share no ordering, so a
#: rule that picks "the catalog" must use the right one.
#:
#: skillsaw claims only the first for Grok. The second is Claude's file —
#: the schemas differ, so linting one against both would contradict itself —
#: and the third is a bare root filename no ecosystem reserves.
CATALOG_PATHS = (
    (PLUGIN_DIR_NAME, MARKETPLACE_FILENAME),
    (".claude-plugin", MARKETPLACE_FILENAME),
    (MARKETPLACE_FILENAME,),
)

#: Where a ``plugin-index.json`` is never read: beside either catalog
#: location Grok falls back to, once ``.grok-plugin/marketplace.json`` has
#: won. Derived from :data:`CATALOG_PATHS` rather than restated, so a change
#: to the fallbacks moves this with it.
UNREAD_INDEX_DIRS = tuple(parts[:-1] for parts in CATALOG_PATHS[1:])

#: Where a plugin's manifest may live, in the order Grok resolves them —
#: verified by building plugins carrying each combination and reading back
#: ``grok plugin validate``: a plugin with all three resolved to the root
#: one, ``.grok-plugin`` + ``.claude-plugin`` resolved to ``.grok-plugin``,
#: and a ``.claude-plugin``-only plugin loaded. The official
#: ``plugin_catalog.py`` lists the last two in the same order.
MANIFEST_PATHS = (
    (PLUGIN_MANIFEST,),
    (PLUGIN_DIR_NAME, PLUGIN_MANIFEST),
    (".claude-plugin", PLUGIN_MANIFEST),
)

#: Every manifest key Grok's loader reads. Unknown keys are tolerated, so
#: this is the vocabulary a rule may check the *shape* of, never a
#: whitelist to report against.
#: Reserved: no rule reads this yet.
MANIFEST_KEYS = frozenset(
    {
        "name",
        "version",
        "description",
        "author",
        "homepage",
        "repository",
        "license",
        "keywords",
        "logo",
        "skills",
        "commands",
        "agents",
        "hooks",
        "mcpServers",
        "lspServers",
    }
)

#: Each component's conventional path, the manifest key that overrides it,
#: and whether the path names a directory. Grok discovers components from
#: these locations with no manifest at all.
#:
#: The two readers disagree about what a manifest key then does, and the
#: binary is the one that matters: the official ``plugin_catalog.py`` unions
#: the declared paths with the conventional directory, while the runtime
#: **replaces** it — ``"skills": ["custom"]`` loaded ``custom`` and nothing
#: from ``skills/``. So a plugin that validates against the catalog tool
#: still loses everything under the conventional directory when Grok loads
#: it, which is what ``grok-plugin-json-valid`` warns about. skillsaw's skill
#: walk visits the conventional directory either way, so the skills that
#: warning names as dropped are still linted.
#:
#: What a path *loads* differs by field, measured against 1.0.13. ``skills``
#: is walked recursively from the declared or conventional root, and the root
#: itself is a skill when it holds a ``SKILL.md``: ``{"skills":
#: ["./skills/postiz"]}`` loaded ``postiz``, ``{"skills": "./"}`` loaded a
#: root ``SKILL.md``, and ``skills/a/b/c/SKILL.md`` loaded under a bare
#: ``skills/``, with no pruning at the first hit. ``commands`` and ``agents``
#: are flat — only a ``*.md`` directly inside the directory loads.
#:
#: ``lspServers`` is vocabulary only — no public schema and no LSP entries
#: in the official marketplace, so nothing calibrates a rule.
COMPONENT_PATHS = {
    "skills": ("skills", True),
    "commands": ("commands", True),
    "agents": ("agents", True),
    "hooks": ("hooks/hooks.json", False),
    "mcpServers": (".mcp.json", False),
    "lspServers": (".lsp.json", False),
}

#: The two fields Grok reads as one path *or* one inline object. Neither
#: arm is an array: measured, ``"hooks": ["hooks/hooks.json"]`` loaded as an
#: empty inline document (``hookType: "inline"``, no target) while the same
#: file named as a bare string loaded as a file, and
#: ``"mcpServers": ["servers.json"]`` loaded no servers at all.
SINGLE_PATH_FIELDS = frozenset({"hooks", "mcpServers"})

#: The plugin name Grok accepts, measured against the binary rather than
#: read off the docs: ``-lead``, ``trail-``, ``UPPER``, ``under_score``,
#: ``dot.name`` and ``""`` are rejected, while ``123``, ``a``, ``a--b`` and
#: 64 characters are accepted and 65 are not. The loader's own message is
#: "must be 1-64 chars, lowercase alphanumeric + hyphens, no leading/trailing
#: hyphens". Anchored with ``\A``/``\Z`` and read with ``fullmatch``: ``$``
#: also matches before a final newline, and ``"tide-charts\n"`` is a name
#: the loader refuses.
PLUGIN_NAME_RE = re.compile(r"\A[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?\Z")
PLUGIN_NAME_MAX_LENGTH = 64

#: The ``sha`` a url source must pin. An absent one degrades to an unpinned
#: ``git clone``, so a vendor force-push ships to every user. The installer
#: accepts 40 or 64 (SHA-256) and is **case-insensitive**: an uppercase
#: 40-hex value passed straight through to fetch-by-sha when measured, so
#: this matches what the runtime pins, and only a branch, a tag, an
#: abbreviation or an absent value is unpinned. The upstream validator
#: requires 40 lowercase, which is stricter than the runtime and owes that
#: its own, softer finding.
SHA_LENGTHS = frozenset({40, 64})
SHA_RE = re.compile(r"\A(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z")

#: The length ``validate-catalog.py`` in ``xai-org/plugin-marketplace``
#: requires, in lowercase. A submission prepared against that CI is the
#: likely reader of this rule, so the gap between it and the runtime is
#: worth one advisory.
UPSTREAM_SHA_LENGTH = 40


def grok_marketplace_relative_path(value: Any) -> Optional[str]:
    """Normalize a catalog path, or return ``None`` for invalid coordinates.

    Grok 1.0.13's ``MarketplaceRelativePath::parse`` strips one leading
    ``./`` before splitting on either slash. Empty, current-directory,
    parent and colon-containing components are rejected, including a root
    source, trailing separator or repeated separator. No whitespace is
    stripped. Filesystem containment must still be checked after parsing.

    This is the catalog's contract, for local sources and remote subdirs;
    plugin manifest component paths use a different loader.
    """
    if not isinstance(value, str):
        return None
    parts = value.removeprefix("./").replace("\\", "/").split("/")
    if any(part in ("", ".", "..") or ":" in part for part in parts):
        return None
    return "/".join(parts)


def grok_local_source_path(source: Any) -> Optional[str]:
    """Normalized valid local catalog path, or ``None`` for any other source.

    The loader keys on ``path`` alone, verified by installing from six
    catalogs differing only in this field: ``{"type": "local", "path": …}``,
    ``{"source": "local", "path": …}``, the bare string ``"./plugins/x"``,
    an object with **no discriminator at all**, and one with a **bogus**
    ``type`` all installed identically. Requiring a discriminator is
    therefore a false positive on catalogs that work.

    A ``url`` is what makes an entry remote. The official catalog's
    subdirectory form — ``{"source": "url", "url": …, "sha": …, "path":
    "plugins/mongodb"}`` — carries a ``path`` that names a directory inside
    the *cloned* repository, so reading it as a local source would resolve
    a plugin directory the checkout does not have.
    """
    if isinstance(source, str):
        return grok_marketplace_relative_path(source)
    if not isinstance(source, dict) or is_url_source(source):
        return None
    return grok_marketplace_relative_path(source.get("path"))


def is_url_source(source: Any) -> bool:
    """Whether *source* names a remote repository to clone.

    ``IndexSource::is_remote`` tests whether its optional URL is set.
    Null or an absent URL leaves a local source, regardless of ``source``
    or ``type`` discriminators. An empty or mistyped non-null URL must not
    fall back to claiming a local path; the catalog rule reports it.
    """
    return isinstance(source, dict) and source.get("url") is not None


def grok_manifest_path(plugin_dir: Path) -> Optional[Path]:
    """The manifest *plugin_dir* resolves to, following :data:`MANIFEST_PATHS`.

    Contained: a manifest resolving outside the plugin is another plugin's,
    and Grok skips it too ("manifest path escapes plugin root; skipping").
    """
    root = safe_resolve(plugin_dir)
    if root is None:
        return None
    for parts in MANIFEST_PATHS:
        candidate = plugin_dir.joinpath(*parts)
        if contained_resolve(candidate, root) is None:
            continue
        if safe_is_file(candidate):
            return candidate
    return None


def grok_manifest(plugin_dir: Path) -> Dict[str, Any]:
    """A Grok plugin's parsed manifest, or ``{}`` when absent or unparseable.

    Uses the shared cached reader: strips a UTF-8 BOM, and repeated reads
    cost nothing.
    """
    path = grok_manifest_path(plugin_dir)
    if path is None:
        return {}
    data, error = read_json(path)
    return data if not error and isinstance(data, dict) else {}


def grok_plugin_name(plugin_dir: Path) -> str:
    """Name a Grok plugin declares, falling back to its directory name."""
    name = grok_manifest(plugin_dir).get("name")
    return name if isinstance(name, str) and name else plugin_dir.name


def grok_declared_paths(plugin_dir: Path, field: str, want_dir: bool) -> List[Path]:
    """Contained paths a Grok manifest names in *field*.

    ``skills``, ``commands`` and ``agents`` accept a path or an array of
    paths; :data:`SINGLE_PATH_FIELDS` accept one path or the object itself,
    which :func:`grok_inline_hooks` and :func:`grok_inline_mcp` read. Paths
    escaping the plugin root are dropped — Grok drops them too, silently,
    which is what makes them worth reporting elsewhere rather than following
    here.
    """
    declared = grok_manifest(plugin_dir).get(field)
    if isinstance(declared, list):
        candidates: List[Any] = [] if field in SINGLE_PATH_FIELDS else list(declared)
    else:
        candidates = [declared]
    root = safe_resolve(plugin_dir)
    if root is None:
        return []
    found: List[Path] = []
    seen: Set[Path] = set()
    for item in candidates:
        if not isinstance(item, str) or not item:
            continue
        candidate = contained_resolve(plugin_dir / item, root)
        if candidate is None or candidate in seen:
            # Two spellings of one path are one component list, and every
            # caller walks what it gets back — a directory listed twice
            # would be read twice.
            continue
        seen.add(candidate)
        if candidate == root and not want_dir:
            continue
        if safe_is_dir(candidate) if want_dir else safe_is_file(candidate):
            found.append(candidate)
    return found


def grok_declared_skill_dirs(plugin_dir: Path) -> List[Path]:
    """Skill directories a Grok manifest declares through ``skills``."""
    return grok_declared_paths(plugin_dir, "skills", want_dir=True)


def grok_declared_hook_files(plugin_dir: Path) -> List[Path]:
    """Hook files a Grok manifest declares through ``hooks``."""
    return grok_declared_paths(plugin_dir, "hooks", want_dir=False)


def grok_declared_mcp_files(plugin_dir: Path) -> List[Path]:
    """MCP config files a Grok manifest declares through ``mcpServers``."""
    return grok_declared_paths(plugin_dir, "mcpServers", want_dir=False)


def _grok_inline(plugin_dir: Path, field: str) -> List[Dict[str, Any]]:
    """The inline object *field* declares, as one document.

    ``inline_documents`` also unpacks an *array* of objects, which Codex
    accepts and Grok does not: a list-valued ``hooks`` loaded an empty
    inline document when measured and a list-valued ``mcpServers`` loaded no
    servers at all, so only the object arm is followed here.
    """
    declared = grok_manifest(plugin_dir).get(field)
    return inline_documents(declared, field) if isinstance(declared, dict) else []


def grok_inline_hooks(plugin_dir: Path) -> List[Dict[str, Any]]:
    """Hooks a Grok manifest declares inline, in hooks.json shape.

    The path form is :func:`grok_declared_hook_files`; this is the object
    form, which carries the same executable commands — the binary logs
    "plugin uses inline hooks in manifest" when it loads one.
    """
    return _grok_inline(plugin_dir, "hooks")


def grok_inline_mcp(plugin_dir: Path) -> List[Dict[str, Any]]:
    """MCP servers a Grok manifest declares inline.

    The counterpart of :func:`grok_inline_hooks` for ``mcpServers``, logged
    as "plugin uses inline mcpServers in manifest". Both ``{"mcpServers":
    {...}}`` and a bare server map are accepted, matching what
    ``McpBlock.servers`` reads.
    """
    return _grok_inline(plugin_dir, "mcpServers")


def grok_manifest_is_contained(plugin_dir: Path) -> bool:
    """Whether *plugin_dir* carries a Grok manifest of its own.

    ``.grok-plugin/plugin.json`` only, never the ``.claude-plugin`` or root
    fallbacks: those are another ecosystem's declaration, and reading them
    as Grok evidence would make every Claude plugin a Grok plugin too.
    Containment is checked the way discovery checks it, so a marker or a
    manifest symlinked out of the plugin is not this plugin's.
    """
    root = safe_resolve(plugin_dir)
    if root is None:
        return False
    marker = plugin_dir / PLUGIN_DIR_NAME
    if contained_resolve(marker, root) is None:
        return False
    manifest = marker / PLUGIN_MANIFEST
    if contained_resolve(manifest, root) is None:
        return False
    return safe_is_file(manifest)


def grok_marker_escapes(plugin_dir: Path) -> bool:
    """Whether *plugin_dir*'s ``.grok-plugin`` marker points out of the plugin.

    The containment half of :func:`grok_manifest_is_contained`, asked
    without requiring the manifest to exist: a directory carrying no marker
    at all does not escape, so a catalog claim over it still stands. A
    marker (or a ``plugin.json`` inside it) that resolves elsewhere is
    another plugin's, and no claim may adopt it.
    """
    root = safe_resolve(plugin_dir)
    if root is None:
        # Containment cannot be proven, so fail closed.
        return True
    marker = plugin_dir / PLUGIN_DIR_NAME
    if not (safe_exists(marker) or safe_is_symlink(marker)):
        return False
    if contained_resolve(marker, root) is None:
        return True
    manifest = marker / PLUGIN_MANIFEST
    return safe_exists(manifest) and contained_resolve(manifest, root) is None
