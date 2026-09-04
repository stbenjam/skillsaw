r"""Google Antigravity repository-context vocabulary, in one place.

Google Antigravity is Google's agentic coding platform. A checkout
configures its CLI (``agy``) through a *customization root* — ``.agents/``,
``.agent/``, ``_agents/`` or ``_agent/`` — holding lifecycle hooks in
``hooks.json``, MCP servers in ``mcp_config.json``, always-on prose in
``rules/**/*.md``, portable Agent Skills in ``skills/``, subagents in
``agents/``, plugins in ``plugins/<name>/``, and the registries listed in
:data:`REGISTRY_FILENAMES`.

Sources:

* Measured against ``agy`` 1.1.25 (``agy changelog`` head; the language
  server logs the same version). Method: an isolated ``HOME`` — the real
  ``~/.gemini`` never read or written — outbound proxies pointed at a dead
  port, one fixture per case, read back from ``agy agents``, ``agy mcp
  list``, ``agy plugin validate`` and the ``--log-file`` diagnostics
  (``hooks_manager.go``, ``discovery.go``, ``plugins.go``). A workspace is
  reported only when passed with ``--add-dir``; the CWD alone is not
  enough, which is a property of these subcommands rather than of the
  layout. No model turn ever ran (``agy --print`` blocks on OAuth), so
  every hooks fact below is about *loading*, never about dispatch.
* The vendor documentation the binary embeds verbatim as string blobs
  (``# Lifecycle Hooks (hooks.json)``, ``# MCP Servers
  (mcp_config.json)``, ``# Plugins``, ``# JSON Configuration Files``,
  ``# Antigravity Customization System Guide``), quoted where it settles a
  point runtime could not. Marked "documented" wherever that is the only
  evidence.
* https://antigravity.google/docs/mcp/ (read 2026-09-03), which names the
  workspace ``mcp_config.json`` location the embedded copy omits.

**Failure scopes.** They differ per file and are what makes a defect worth
reporting:

* ``hooks.json`` — every load-time rejection is **file-scoped and
  non-fatal**. The file contributes zero hooks, one ``failed to parse
  hooks.json at <path>: <err>`` is logged, and ``agy`` still exits 0. There
  is no entry-scoped rejection and no startup abort.
* ``mcp_config.json`` — a JSON syntax error or a non-object root is
  **startup-fatal** (exit 1, one message naming the file). Any per-server
  shape problem drops **that server only, silently**. There is no middle
  ground and no per-server diagnostic.
* ``plugin.json`` — a manifest that does not parse means the directory is
  not a plugin at all: it is skipped with one ``plugins.go`` line.
* A registry — a non-object root logs one ``Failed to load JSON config
  file`` line and that file is skipped.

**What was not observable offline.** Whether a workspace or plugin
``mcp_config.json`` is read at all (``agy mcp list`` and ``agy mcp add``
are home-only; the shape matrix below was obtained at the global path,
which exercises the same parser); skill discovery (no listing command);
``skills.json`` and ``workflows.json`` as loaders (``agy agents`` queries
only the agents and plugins kinds); and every runtime hook behaviour,
including what a ``matcher`` is compiled with.
"""

from __future__ import annotations

import re

#: The four customization roots, measured: a ``hooks.json`` or an
#: ``agents/<n>.md`` under each is honoured. Discovery walks **up** from
#: the entry directory to the repository root and unions every root it
#: finds on the way; it never descends, and a ``.git`` directory is not
#: required. ``.gemini/`` and ``.antigravity/`` are deliberately absent —
#: neither is read from a workspace.
ANTIGRAVITY_CONFIG_DIR_NAMES = (".agents", ".agent", "_agents", "_agent")

#: The plugin marker, a direct child of ``<root>/plugins/`` only: a nested
#: ``plugins/outer/inner/plugin.json`` is not discovered, and a directory
#: named by a sibling catalog but carrying no manifest is not a plugin.
PLUGIN_MANIFEST = "plugin.json"

#: Lifecycle hooks, one file per customization root and one per plugin.
HOOKS_FILENAME = "hooks.json"

#: MCP servers, one file per customization root and one per plugin.
MCP_CONFIG_FILENAME = "mcp_config.json"

#: Component directories under a customization root. ``rules/`` is read
#: recursively as always-on prose and ``agents/`` holds subagents, so both
#: are attached here. Two more are named by the host and belong elsewhere:
#: ``skills/`` is the portable Agent Skills convention, walked through
#: ``CONVENTIONAL_SKILL_DIRS``, which earns the whole skill rule set; and
#: ``plugins/`` is the install location, which belongs to plugin discovery.
#: A plugin adds a ``commands/`` that ``agy plugin validate`` reports as
#: "converted to skills"; the shared plugin-prose attach reads it.
RULES_DIR_NAME = "rules"
AGENTS_DIR_NAME = "agents"
PLUGINS_DIR_NAME = "plugins"

#: Registry files a customization root may carry, each a
#: ``customizations.JSONConfig`` document naming where else to load that
#: kind of customization from. ``agents.json`` and ``plugins.json`` are
#: measured (a non-object root logs ``Failed to load JSON config file``);
#: ``skills.json`` is documented; ``workflows.json`` is named by the
#: embedded migrate-workflows skill, which spells out all four roots. A
#: ``rules.json`` literal exists in the binary but no loader was reached
#: for it, so it is deliberately not here.
REGISTRY_FILENAMES = ("agents.json", "plugins.json", "skills.json", "workflows.json")

#: The four fields ``plugin.json`` carries meaning in. The manifest is a
#: **protojson** message (errors read ``proto: (line 1:9): invalid value
#: for string field name: 42``), so every other key — ``$schema``,
#: ``version``, ``author``, ``mcpServers``, ``hooks`` — is discarded as
#: unknown and the plugin still loads. Measured by giving each candidate
#: key a wrong-typed value and reading the type error back.
PLUGIN_MESSAGE_FIELDS = (
    ("name", str, "string"),
    ("description", str, "string"),
    ("disabled", bool, "boolean"),
    ("logo", str, "string"),
)

#: Names ``agy plugin validate`` and ``agy plugin install`` accept.
#: Discovery enforces nothing — ``{"name": "has spaces"}`` and ``{"name":
#: "a/b"}`` both load, and a manifest with no ``name`` at all defaults to
#: the directory name — but ``install`` refuses both, and ``.hidden`` with
#: them, so a committed manifest that cannot be installed is worth a word.
PLUGIN_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")

#: Events whose value is a list of ``{matcher, hooks: [handler, ...]}``
#: groups (``[]jsonhook.ToolHookGroup``).
TOOL_HOOK_EVENTS = frozenset({"PreToolUse", "PostToolUse"})

#: Events whose value is a flat handler list (``[]jsonhook.HookHandler``).
#: ``SessionStart`` is undocumented and real — the binary binds it like the
#: other three.
FLAT_HOOK_EVENTS = frozenset({"PreInvocation", "PostInvocation", "Stop", "SessionStart"})

HOOK_EVENTS = TOOL_HOOK_EVENTS | FLAT_HOOK_EVENTS

#: Event keys bind **case-insensitively**: ``{"n": {"pretooluse": 5}}``
#: reports ``cannot unmarshal number into Go struct field .n.pretooluse of
#: type []jsonhook.ToolHookGroup``, so ``pretooluse`` reached ``PreToolUse``.
#: A rule that flags a lower-cased event name as unknown is a false positive.
HOOK_EVENTS_BY_CASEFOLD = {name.casefold(): name for name in HOOK_EVENTS}

#: An unknown event key is **silently ignored**: no error, no counter
#: change, and the hook it holds never runs.
#:
#: Handler types. ``command`` is the default when ``type`` is absent or
#: ``""``; ``prompt`` is real (``prompt hook cannot specify 'command'``
#: proves the branch). Any other value fails the file, and the comparison
#: is case-sensitive — ``"COMMAND"`` is rejected.
HOOK_HANDLER_TYPES = frozenset({"command", "prompt"})

#: ``hookHandlerJSON``'s fields. Anything else on a handler — ``name``,
#: ``env``, ``cwd``, ``enabled`` — is silently ignored, so a hook written
#: with one never does what its author expects.
HOOK_HANDLER_KEYS = frozenset({"type", "command", "prompt", "model", "timeout"})

#: ``timeout``'s bounds. It is a Go ``int32``, and the range is the whole
#: of the check: ``0`` and negatives load, while ``2147483648`` fails the
#: file with the same ``cannot unmarshal number … of type int32`` a float
#: or a string draws — measured at both ends.
HOOK_TIMEOUT_MIN = -(2**31)
HOOK_TIMEOUT_MAX = 2**31 - 1

#: ``ToolHookGroup``'s fields. ``type``, ``command``, ``tools`` and
#: ``event`` inside a group are silently ignored.
#:
#: ``matcher`` must be a string and is **never compiled at load** —
#: ``"[unclosed"`` loads clean — so no linter can claim ``agy`` will reject
#: a pattern, and skillsaw compiles nothing here. ``""`` and ``"*"`` are the
#: documented catch-alls. The engine is unproven: the binary is Go and
#: carries ``regexp/syntax`` types, which implies RE2, but no run
#: demonstrated it.
HOOK_GROUP_KEYS = frozenset({"matcher", "hooks"})

#: Per-named-hook fields that are not events. ``enabled`` is documented as
#: the per-hook switch. At the **top level** ``enabled`` is not a switch at
#: all: every top-level key is a hook *name*, so a boolean there is a hard
#: parse error (``cannot unmarshal bool into Go struct field .enabled of
#: type jsonhook.JSONHookSpec``) that kills the file.
HOOK_SPEC_NON_EVENT_KEYS = frozenset({"enabled"})

#: Per-server maps in ``mcp_config.json`` whose values may hold a committed
#: credential, as ``(key, is_http_header)``. All three are measured to
#: load: ``env``, ``headers``, and ``oauth`` carrying ``clientId`` /
#: ``clientSecret``.
MCP_CREDENTIAL_MAPS = (("env", False), ("headers", True), ("oauth", False))

#: The same two keys spelled at a server's own top level, where they are
#: scalars rather than a map. Measured to load there too, so a secret
#: written this way ships and runs exactly like one inside ``oauth``.
MCP_CREDENTIAL_FIELDS = ("clientId", "clientSecret")

#: The ``oauth`` map's keys, renamed to the snake_case spelling the shared
#: credential-*name* detector knows. Without this ``clientSecret`` reads as
#: an unremarkable key and a literal secret under it goes unreported.
MCP_CREDENTIAL_KEY_ALIASES = {"clientId": "client_id", "clientSecret": "client_secret"}
