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

* **Whole file** — malformed JSON; a bare ``NaN``, ``Infinity`` or
  ``-Infinity`` token, which Python's ``json`` accepts as a float and
  ``serde_json`` refuses; no top-level ``hooks`` object; an event whose
  value is not an array; a matcher group that is not an object; a group
  with no ``hooks`` key or a non-array one; a handler that is not an
  object; a handler with no ``type``; and any field in
  :data:`HANDLER_FIELDS` carrying the wrong JSON type. One mistyped
  ``timeout`` costs the author every hook in the file.
* **That matcher group** — a ``matcher`` string that does not compile.
* **That event's entries** — an event name outside :data:`HOOK_EVENTS` and
  :data:`HOOK_EVENT_ALIASES`. The rest of the file loads.
* **That handler** — a ``command`` handler with no ``command``, an ``http``
  handler with no ``url``, or a ``type`` outside
  :data:`HOOK_HANDLER_TYPES`. Sibling handlers still run.
* **Tolerated** — an unknown key on a handler, on a matcher group
  (``description``), or at the top level; an empty ``hooks`` array; an
  empty ``matcher``.

``matcher`` is a regex Grok compiles at load time with Rust's ``regex``
crate — verified by loading ``\p{L}+`` and ``[a-z&&[^aeiou]]``, which
Python's ``re`` rejects, and by watching ``(?<=x)y`` and ``(a)\1`` drop
their groups, which Rust rejects and Python accepts. ``""`` and ``"*"`` are
both catch-alls rather than patterns. What the matcher tests depends on the
event; on the two events in :data:`MATCHER_IGNORED_EVENTS` it is kept in
the configuration and ignored at dispatch.
"""

from __future__ import annotations

from typing import Any, Mapping

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

#: Project configuration and LSP servers. Neither is parsed yet — file
#: existence alone is what makes the directory Grok's.
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
#: :data:`CONFIG_FILENAME`: Grok configuration nothing here parses or
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
