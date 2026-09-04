"""Antigravity filenames and loader vocabulary.

Verified against agy 1.1.25, with follow-up checks on 1.1.26. The measured
inputs, observables and limitations live in the maintenance reference at
``.apm/skills/skillsaw-maintenance/references/antigravity.md``.

Official docs: https://antigravity.google/docs/hooks/ and
https://antigravity.google/docs/cli/plugins/. The published plugin schema
is narrower than the loader; the field set below follows the loader.
"""

from __future__ import annotations

import re
from types import MappingProxyType

#: The four customization roots, measured: a ``hooks.json`` or an
#: ``agents/<n>.md`` under each is honoured. Discovery walks **up** from
#: the entry directory to the repository root and unions every root it
#: finds on the way; it never descends, and a ``.git`` directory is not
#: required. ``.gemini/`` and ``.antigravity/`` are deliberately absent —
#: neither is read from a workspace.
ANTIGRAVITY_CONFIG_DIR_NAMES = (".agents", ".agent", "_agents", "_agent")

#: The roots whose *name* belongs to this host alone. ``.agent/`` is the
#: documented Windsurf-lineage back-compat path and no other tool reads it,
#: so a populated ``rules/`` or ``agents/`` under it is evidence of
#: Antigravity. The other three are shared or ordinary names: ``.agents/``
#: is tool-neutral, while ``_agents/`` and ``_agent/`` may name source packages.
#: Detection there requires an Antigravity-specific file.
EXCLUSIVE_ROOT_NAMES = frozenset({".agent"})

#: The plugin marker. Automatic discovery checks ``<root>/plugins/*``;
#: a registry can also name a manifest-bearing directory elsewhere.
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

#: The two registries whose ``entries`` the lint tree resolves. Both are
#: measured end to end — a ``plugins.json`` naming a container loads every
#: plugin under it, an ``agents.json`` naming a directory loads the agents
#: in it — so what they point at is part of the repository's configuration.
#: ``skills.json`` and ``workflows.json`` stay out: neither could be
#: triggered as a loader offline, and resolving an unmeasured one would
#: attach content on a guess.
AGENTS_REGISTRY = "agents.json"
PLUGINS_REGISTRY = "plugins.json"

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

#: Names ``agy plugin install`` accepts.
#: Discovery enforces nothing — ``{"name": "has spaces"}`` and ``{"name":
#: "a/b"}`` both load, and a manifest with no ``name`` at all defaults to
#: the directory name — but ``install`` refuses both, and ``.hidden`` with
#: them, so a committed manifest that cannot be installed is worth a word.
#: ``agy plugin validate`` is not the check: it prints ``[ok]`` for
#: ``has spaces`` and for a trailing newline, while ``install`` exits 1 with
#: ``Error: invalid plugin name``.
#: Anchored with ``\A``/``\Z`` and read with ``fullmatch``: ``$`` also
#: matches before a final newline, and a JSON string can hold one, so
#: ``{"name": "berth-tools\n"}`` would otherwise read as installable.
PLUGIN_NAME_RE = re.compile(r"\A[A-Za-z0-9_-]+\Z")

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
#: An unknown event key is **silently ignored**: no error, no counter
#: change, and the hook it holds never runs.
HOOK_EVENTS_BY_CASEFOLD = MappingProxyType({name.casefold(): name for name in HOOK_EVENTS})

#: Handler types. ``command`` is the default when ``type`` is absent or
#: ``""``; ``prompt`` is real (``prompt hook cannot specify 'command'``
#: proves the branch). Any other value fails the file, and the comparison
#: is case-sensitive — ``"COMMAND"`` is rejected.
HOOK_HANDLER_TYPES = frozenset({"command", "prompt"})

#: ``hookHandlerJSON``'s fields. Anything else on a handler — ``name``,
#: ``env``, ``cwd``, ``enabled`` — is silently ignored, so a hook written
#: with one never does what its author expects.
HOOK_HANDLER_KEYS = frozenset({"type", "command", "prompt", "model", "timeout"})

#: The subset of :data:`HOOK_HANDLER_KEYS` whose presence means the entry
#: declares a handler *of its own*, as opposed to being a pure
#: ``{matcher, hooks}`` group. Read by the security rendering, which shows
#: the scanners both readings of every entry and must not manufacture an
#: empty handler for a group.
HOOK_HANDLER_COMMAND_KEYS = ("command", "prompt", "type")

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
#: all: every top-level key is a hook *name*, so ``{"enabled": {"Stop":
#: [...]}}`` loads as a hook called ``enabled`` and only a non-object value
#: is a hard parse error (``cannot unmarshal bool into Go struct field
#: .enabled of type jsonhook.JSONHookSpec``) that kills the file.
HOOK_SPEC_NON_EVENT_KEYS = frozenset({"enabled"})

#: Top-level keys an author writes meaning file-level metadata, which this
#: host reads as hook *names*. Each gets its own message saying so, because
#: "a named hook must be a JSON object" tells the author nothing about why
#: their schema reference or version stamp broke the file.
HOOK_METADATA_KEY_HINTS = MappingProxyType(
    {
        "enabled": "'enabled' belongs inside a named hook",
        "$schema": "Antigravity publishes no hooks schema, so drop the key",
        "version": "this document carries no version field",
    }
)

#: The one value ``authProviderType`` parses. The proto enum also spells it
#: ``MCP_AUTH_PROVIDER_TYPE_GOOGLE_CREDENTIALS``, and that spelling drops
#: the server — only the lowercase JSON alias is accepted. Measured:
#: ``"oauth"``, either enum spelling, and a bare ``1`` are each dropped
#: silently.
MCP_AUTH_PROVIDER_TYPES = frozenset({"google_credentials"})

#: Per-server string fields whose wrong type drops the server, measured
#: with ``agy mcp list`` against a clean sibling. ``type`` is deliberately
#: absent: a non-string there is tolerated and the server still loads.
MCP_STRING_FIELDS = ("command", "url", "serverUrl", "cwd")

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
MCP_CREDENTIAL_KEY_ALIASES = MappingProxyType(
    {"clientId": "client_id", "clientSecret": "client_secret"}
)
