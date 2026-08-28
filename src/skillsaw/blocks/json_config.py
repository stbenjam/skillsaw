"""Structured JSON configuration blocks: hooks, MCP, and settings.

These deliberately subclass :class:`LintTarget` (not ``ContentBlock``): they
are machine configuration, not prose for an agent's context window, so
content-quality rules never see them.  Dedicated rules locate them with
``find(HooksBlock)`` etc. and read ``raw_data``/``parse_error``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, ClassVar, Dict, List, Mapping, Optional, Set, Tuple

from skillsaw.formats.opencode import MCP_OAUTH_V1_TO_V2
from skillsaw.lint_target import LintTarget
from skillsaw.utils import read_text, read_json, read_json_strict, read_jsonc


def _as_str(value: Any) -> Optional[str]:
    """*value* when it is a string, else ``None``."""
    return value if isinstance(value, str) else None


def _as_str_list(value: Any) -> Optional[List[str]]:
    """*value* with non-string members filtered out, or ``None`` for non-lists.

    A bare string is not a list of arguments — iterating it would split
    the value into characters and scan each one.
    """
    if not isinstance(value, list):
        return None
    return [v for v in value if isinstance(v, str)]


@dataclass
class HookHandler:
    """A single hook handler entry."""

    type: str
    command: Optional[str] = None
    args: Optional[List[str]] = None
    url: Optional[str] = None
    headers: Optional[Dict[str, Any]] = None
    server: Optional[str] = None
    tool: Optional[str] = None
    input: Optional[Dict[str, Any]] = None
    prompt: Optional[str] = None
    model: Optional[str] = None
    timeout: Optional[float] = None
    async_: Optional[bool] = None
    async_rewake: Optional[bool] = None
    once: Optional[bool] = None
    if_: Optional[str] = None
    status_message: Optional[str] = None
    shell: Optional[str] = None
    allowed_env_vars: Optional[List[str]] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "HookHandler":
        """Build a handler from raw JSON, dropping values of the wrong type.

        The annotations here are a contract the JSON cannot be trusted to
        honour: ``{"type": "command", "command": ["curl", "..."]}`` is
        syntactically fine, and every consumer that joins or regex-scans
        ``command`` as a string raises ``TypeError`` on it. In
        ``hooks-dangerous`` that becomes a rule crash, which stops the scan
        before it reaches later blocks — so one malformed handler can hide
        a real ``curl | sh`` behind it. Dropping the value here leaves the
        field falsy, which every consumer already handles, and
        ``hooks-json-valid`` reads the raw document and reports the shape.
        """
        return cls(
            type=_as_str(d.get("type")) or "",
            command=_as_str(d.get("command")),
            args=_as_str_list(d.get("args")),
            url=_as_str(d.get("url")),
            headers=d.get("headers"),
            server=_as_str(d.get("server")),
            tool=_as_str(d.get("tool")),
            input=d.get("input"),
            prompt=_as_str(d.get("prompt")),
            model=_as_str(d.get("model")),
            timeout=d.get("timeout"),
            async_=d.get("async"),
            async_rewake=d.get("asyncRewake"),
            once=d.get("once"),
            if_=_as_str(d.get("if")),
            status_message=_as_str(d.get("statusMessage")),
            shell=_as_str(d.get("shell")),
            allowed_env_vars=_as_str_list(d.get("allowedEnvVars")),
        )


@dataclass
class HookEventConfig:
    """A single event config entry (matcher + handlers)."""

    matcher: str = ".*"
    handlers: List[HookHandler] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "HookEventConfig":
        handlers: List[HookHandler] = []
        raw_hooks = d.get("hooks", [])
        if isinstance(raw_hooks, list):
            for h in raw_hooks:
                if isinstance(h, dict):
                    handlers.append(HookHandler.from_dict(h))
        return cls(
            # Coerced like the handler fields: a list-valued matcher reaches
            # every consumer annotated ``str``, and the generated docs page
            # lowercases it while searching, which kills search for the
            # whole page. Codex uses the default when the field is absent,
            # and an invalid value is no more specific than absent.
            # hooks-json-valid reports it, so coercing hides nothing.
            matcher=_as_str(d.get("matcher")) or ".*",
            handlers=handlers,
        )


def parse_hooks_events(hooks_obj: Any) -> Dict[str, List[HookEventConfig]]:
    """Parse a ``hooks`` object into event configs.

    Supports both the nested (hooks.json / settings.json) format
    ``{ EventType: [{ matcher, hooks: [{type, command}] }] }`` and the flat
    settings shorthand ``{ EventType: [{ type, command, matcher? }] }``.  The
    same schema is accepted in skill/agent frontmatter ``hooks:`` keys.
    """
    if not isinstance(hooks_obj, dict):
        return {}
    result: Dict[str, List[HookEventConfig]] = {}
    for event_type, configs in hooks_obj.items():
        if not isinstance(configs, list):
            continue
        entries: List[HookEventConfig] = []
        for cfg in configs:
            if not isinstance(cfg, dict):
                continue
            if "hooks" in cfg:
                entries.append(HookEventConfig.from_dict(cfg))
            elif "type" in cfg:
                handler = HookHandler.from_dict(cfg)
                matcher = _as_str(cfg.get("matcher")) or ".*"
                entries.append(HookEventConfig(matcher=matcher, handlers=[handler]))
        if entries:
            result[event_type] = entries
    return result


def _parse_json_file(
    path: Path, *, strict: bool = False, jsonc: bool = False
) -> Tuple[Optional[Any], Optional[str]]:
    if jsonc:
        # JSONC is always strict about the non-finite tokens; the locations
        # that opt into it are new surfaces with no shipped results.
        return read_jsonc(path)
    data, error = (read_json_strict if strict else read_json)(path)
    return data, error


@dataclass(eq=False)
class JsonConfigBlock(LintTarget):
    """Structured JSON configuration in the lint tree.

    Deliberately not a :class:`ContentBlock`: these files are machine
    configuration, not prose for an agent's context window, so
    content-quality rules never see them. Dedicated rules locate them
    with ``find(HooksBlock)`` etc. and read ``raw_data``/``parse_error``.
    """

    category: str = ""
    #: Whether to reject ``NaN``/``Infinity`` — tokens ``json.loads`` accepts
    #: and no JSON host does, so the file is unreadable to the tool it
    #: configures. Off by default: the pre-existing block types have shipped
    #: results that a tightened parser would turn into "Invalid JSON" on
    #: upgrade. The locations added since opt in, having no such history.
    strict_json: ClassVar[bool] = False
    #: Whether the host reads this file as JSONC — ``//`` and ``/* */``
    #: comments and a comma before a closing brace. Off by default: every
    #: Claude-family location is strict JSON, and accepting comments there
    #: would stop reporting a file its own host cannot read. A host that
    #: documents JSONC (OpenCode names both ``opencode.json`` and
    #: ``opencode.jsonc``) opts in, so a commented config is not reported
    #: as a parse error. Implies :attr:`strict_json`, which is why the
    #: locations setting this leave that one at its default.
    jsonc: ClassVar[bool] = False
    _parsed: Optional[Tuple[Optional[Any], Optional[str]]] = field(
        default=None, init=False, repr=False
    )

    def _ensure_parsed(self) -> None:
        if self._parsed is None:
            self._parsed = _parse_json_file(self.path, strict=self.strict_json, jsonc=self.jsonc)

    @property
    def parse_error(self) -> Optional[str]:
        self._ensure_parsed()
        return self._parsed[1]

    @property
    def raw_data(self) -> Optional[Dict[str, Any]]:
        self._ensure_parsed()
        data = self._parsed[0]
        return data if isinstance(data, dict) else None

    def estimate_tokens(self) -> int:
        content = read_text(self.path)
        return len(content) // 4 if content else 0

    def tree_label(self) -> str:
        return f"{self.path.name} ({self.category})"


@dataclass(eq=False)
class HooksBlock(JsonConfigBlock):
    """hooks/hooks.json in a plugin."""

    category: str = "hooks"

    @property
    def events(self) -> Dict[str, List[HookEventConfig]]:
        data = self.raw_data
        if data is None:
            return {}
        hooks_obj = data.get("hooks", {})
        if not isinstance(hooks_obj, dict):
            return {}
        result: Dict[str, List[HookEventConfig]] = {}
        for event_type, configs in hooks_obj.items():
            if not isinstance(configs, list):
                continue
            entries: List[HookEventConfig] = []
            for cfg in configs:
                if isinstance(cfg, dict):
                    entries.append(HookEventConfig.from_dict(cfg))
            if entries:
                result[event_type] = entries
        return result


class _InlineJsonPayload:
    """Config that arrived by value in a manifest field, not in a file.

    Several Codex ``plugin.json`` fields take a path *or* the object
    itself. The object form carries the same commands as the file form, so
    it gets the same rules — this supplies the payload the base class would
    otherwise have read off disk. ``path`` stays the manifest, which is
    where the config actually lives and where a violation should point.
    """

    # Declared for type-checkers only: this class is not a dataclass, so
    # each subclass must redeclare it as a real field.
    inline_data: Optional[Dict[str, Any]] = None

    def _ensure_parsed(self) -> None:
        if self._parsed is None:
            self._parsed = (self.inline_data, None)

    def estimate_tokens(self) -> int:
        return len(json.dumps(self.inline_data or {})) // 4

    # LintTarget compares by (type, resolved path), which assumes the path
    # identifies the config. It does not here: a manifest can declare an
    # array of inline objects, so several of these share one path while
    # carrying different payloads. Identity is the only honest key for
    # config that has no file of its own.
    def __eq__(self, other: object) -> bool:
        return self is other

    def __hash__(self) -> int:
        return id(self)


@dataclass(eq=False)
class CodexInlineHooksBlock(_InlineJsonPayload, HooksBlock):
    """Hooks written inline in a Codex ``.codex-plugin/plugin.json``."""

    inline_data: Optional[Dict[str, Any]] = None

    def tree_label(self) -> str:
        return f"{self.path.name} (inline hooks)"


@dataclass(eq=False)
class CursorHooksBlock(JsonConfigBlock):
    """``.cursor/hooks.json`` — Cursor's agent-lifecycle hooks.

    Cursor's shape is flatter than Claude's: ``{version, hooks: {event:
    [{command | prompt, type?, matcher?, timeout?}]}}``. There is no
    per-event ``matcher`` wrapper, and ``type`` defaults to ``"command"``
    rather than being required. :attr:`events` renders it as the shared
    :class:`HookEventConfig` structure so ``hooks-dangerous`` and
    ``hooks-prohibited`` scan Cursor hooks with no per-ecosystem branch;
    ``cursor-hooks-valid`` reads ``raw_data`` for the shape itself.
    """

    category: str = "hooks"
    strict_json: ClassVar[bool] = True

    def tree_label(self) -> str:
        return "hooks.json (cursor hooks)"

    @property
    def events(self) -> Dict[str, List[HookEventConfig]]:
        data = self.raw_data
        if data is None:
            return {}
        hooks_obj = data.get("hooks")
        if not isinstance(hooks_obj, dict):
            return {}
        result: Dict[str, List[HookEventConfig]] = {}
        for event_type, entries in hooks_obj.items():
            if not isinstance(entries, list):
                continue
            configs: List[HookEventConfig] = []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                # ``type`` is optional and defaults to a command hook. Set it
                # explicitly either way: the shared security rules skip any
                # handler whose type is not "command", so leaving it empty
                # would silently exempt every Cursor hook.
                entry_type = _as_str(entry.get("type")) or "command"
                if entry_type != "command":
                    # A prompt hook injects text instead of spawning a
                    # process, so the command scanners have nothing to read.
                    # ``prompt_hooks()`` surfaces its prose separately.
                    continue
                command = _as_str(entry.get("command"))
                if not command:
                    continue
                # One config per entry: Cursor puts ``matcher`` on the hook
                # itself, not on a wrapper shared by several handlers.
                configs.append(
                    HookEventConfig(
                        matcher=_as_str(entry.get("matcher")) or ".*",
                        handlers=[HookHandler(type="command", command=command)],
                    )
                )
            if configs:
                result[event_type] = configs
        return result

    def prompt_hooks(self) -> List[Tuple[str, int, str]]:
        """Return ``(event_type, index, prompt)`` for every prompt hook.

        The complement of :attr:`events`, which covers only the handlers
        that run a command. A prompt hook is still a hook — it fires on the
        same lifecycle events and ships in the same file — but what it
        delivers is text for the model, so it belongs to the content rules
        rather than the command scanners.

        The index is the entry's position in its event's list, which is how
        a violation names one prompt among several on the same event.
        """
        data = self.raw_data
        if data is None:
            return []
        hooks_obj = data.get("hooks")
        if not isinstance(hooks_obj, dict):
            return []
        found: List[Tuple[str, int, str]] = []
        for event_type, entries in hooks_obj.items():
            if not isinstance(entries, list):
                continue
            for index, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    continue
                if _as_str(entry.get("type")) != "prompt":
                    continue
                prompt = _as_str(entry.get("prompt"))
                if prompt:
                    found.append((event_type, index, prompt))
        return found


@dataclass
class McpServerConfig:
    """A single MCP server configuration."""

    name: str
    type: str = "stdio"
    command: Optional[str] = None
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None
    cwd: Optional[str] = None
    url: Optional[str] = None
    headers: Optional[Dict[str, Any]] = None
    headers_helper: Optional[str] = None
    startup_timeout: Optional[float] = None
    timeout: Optional[float] = None
    always_load: Optional[bool] = None
    oauth: Optional[Dict[str, Any]] = None

    @classmethod
    def from_dict(cls, name: str, d: Dict[str, Any]) -> "McpServerConfig":
        return cls(
            name=name,
            type=d.get("type", "stdio"),
            command=d.get("command"),
            args=d.get("args"),
            env=d.get("env"),
            cwd=d.get("cwd"),
            url=d.get("url"),
            headers=d.get("headers"),
            headers_helper=d.get("headersHelper"),
            startup_timeout=d.get("startupTimeout"),
            timeout=d.get("timeout"),
            always_load=d.get("alwaysLoad"),
            oauth=d.get("oauth"),
        )


@dataclass(eq=False)
class McpBlock(JsonConfigBlock):
    """.mcp.json at the project root, inside a plugin, or in ``.cursor/``."""

    category: str = "mcp"

    #: Top-level key holding the server map. Every host but VS Code spells
    #: it ``mcpServers``; see :class:`VsCodeMcpBlock`.
    servers_key: ClassVar[str] = "mcpServers"

    #: Whether a document with no wrapper key is itself the server map.
    #: True for the Claude-family files, where ``.mcp.json`` may be written
    #: either way. A host with other documented top-level keys must set this
    #: False, or those siblings get read as servers.
    allow_bare_server_map: ClassVar[bool] = True
    #: Top-level keys a host documents alongside its server map. Their
    #: presence means a document without the wrapper is deliberately
    #: server-less rather than mis-keyed. Empty for hosts that document no
    #: such sibling, where any other key is a mistake.
    non_server_keys: ClassVar[frozenset] = frozenset()
    #: Editor-agnostic metadata keys that are never a server and never a sign
    #: of a mis-keyed document. ``$schema`` is the schemastore hint editors
    #: add to any JSON file; it must not, on its own, read as "no servers
    #: loaded" beside a legitimately server-less config.
    always_ignored_keys: ClassVar[frozenset] = frozenset({"$schema"})
    #: Whether Claude Code's built-in server names are reserved in this
    #: file. True for the Claude-family locations Claude Code actually
    #: reads; an editor that loads its own MCP config has no such built-ins,
    #: so shadowing is not a thing that can happen there.
    claude_builtins_reserved: ClassVar[bool] = True
    #: Whether the connection field must be *usable* and not merely present.
    #: ``{"command": []}`` names nothing a host can spawn, so the server
    #: never starts. Left False for the Claude-family files, whose results
    #: predate the check and are held stable (a Codex-only plugin opts in
    #: separately, per-path); the editor locations are new surfaces with no
    #: established results to preserve, so they require it from the start.
    require_usable_connection: ClassVar[bool] = False
    #: Per-server maps whose values may hold a committed credential, as
    #: ``(key, is_http_header)``. Declared on the block because the key names
    #: are the host's: every Claude-family host spells the environment map
    #: ``env``, OpenCode spells it ``environment`` and adds ``oauth``. Read
    #: by the checks ``mcp-valid-json`` keeps for a block whose *shape* it
    #: defers, so a host with its own dialect does not lose the credential
    #: scan along with the shape checks.
    credential_maps: ClassVar[Tuple[Tuple[str, bool], ...]] = (
        ("env", False),
        ("headers", True),
    )
    #: Key renames to apply before the credential-*name* test only, for a
    #: host whose older spelling the shared detector cannot split (OpenCode's
    #: 1.x ``clientSecret`` against its 2.0 ``client_secret``). Findings
    #: always name the key as the author wrote it.
    credential_key_aliases: ClassVar[Mapping[str, str]] = MappingProxyType({})

    def server_entries(self) -> List[Tuple[str, Any]]:
        """Every declared server as ``(name, value)``, in document order.

        A list of pairs rather than a mapping, because a host may declare
        one server name twice: OpenCode loads two config layouts at once,
        so a file mid-migration can name the same server in each. A mapping
        would silently keep one of them, and keeping the copy that does
        *not* carry the committed credential is how a scanner reports a
        file clean. Every other host has one layout, where this is exactly
        ``servers_dict.items()``.

        Values are returned unfiltered so a validating caller can report a
        server whose value is not an object at all; :attr:`servers` drops
        those, since there is no configuration to model.

        The seam a host with more than one layout overrides; see
        :class:`OpenCodeMcpBlock`.
        """
        data = self.raw_data
        if data is None:
            return []
        if self.servers_key in data:
            servers_dict = data[self.servers_key]
        elif self.allow_bare_server_map:
            servers_dict = data
        else:
            return []
        if not isinstance(servers_dict, dict):
            return []
        return list(servers_dict.items())

    @property
    def servers(self) -> List[McpServerConfig]:
        return [
            McpServerConfig.from_dict(name, cfg)
            for name, cfg in self.server_entries()
            if isinstance(cfg, dict)
        ]

    @property
    def server_names(self) -> Set[str]:
        return {s.name for s in self.servers}


@dataclass(eq=False)
class AgentPluginMcpBlock(McpBlock):
    """Portable Agent Plugins ``mcp.json`` configuration."""

    def tree_label(self) -> str:
        return "mcp.json (agent plugin MCP)"


@dataclass(eq=False)
class CursorMcpBlock(McpBlock):
    """``.cursor/mcp.json`` — Cursor's MCP configuration.

    Cursor documents exactly one shape, ``{"mcpServers": {...}}``, and no
    bare-map form. Inheriting the Claude-family fallback would read a bare
    map as valid while Cursor loads nothing from it.
    """

    allow_bare_server_map: ClassVar[bool] = False
    claude_builtins_reserved: ClassVar[bool] = False
    require_usable_connection: ClassVar[bool] = True
    strict_json: ClassVar[bool] = True

    def tree_label(self) -> str:
        return "mcp.json (Cursor MCP)"


@dataclass(eq=False)
class VsCodeMcpBlock(McpBlock):
    """``.vscode/mcp.json`` — the Copilot/VS Code MCP configuration.

    Same server shape as every other host, under a different key: VS Code
    spells the map ``servers``, and documents two siblings — ``inputs``
    (prompted variables) and ``sandbox``. Neither is a server, and there is
    no bare-map form here, so a document without ``servers`` declares no
    servers rather than being one.
    """

    servers_key: ClassVar[str] = "servers"
    allow_bare_server_map: ClassVar[bool] = False
    non_server_keys: ClassVar[frozenset] = frozenset({"inputs", "sandbox"})
    claude_builtins_reserved: ClassVar[bool] = False
    require_usable_connection: ClassVar[bool] = True
    strict_json: ClassVar[bool] = True

    def tree_label(self) -> str:
        return "mcp.json (VS Code MCP)"


#: Connection fields that identify one OpenCode server, paired with the type
#: the field has on a server. The *value* type is what does the work: a
#: server may legitimately be *named* ``command`` or ``type``, and matching
#: on names alone would read the map holding it as a single server.
_OPENCODE_CONNECTION_FIELDS = (
    ("type", str),
    ("command", list),
    ("url", str),
)


def _is_opencode_server(value: Any) -> bool:
    """Whether *value* is one OpenCode MCP server rather than a map of them.

    Answers the same ambiguity upstream's ``isDirectServer`` does, though
    not identically — it keys on ``type``/``enabled`` holding a non-object,
    this keys on a connection field of the right type, and the two differ on
    a bare ``{"enabled": true}``. A server carries a connection field; a map
    of servers carries server objects. Testing the value and not just the
    key is what keeps a server named ``command`` — whose ``command`` entry
    is a nested object, not an argv array — from being mistaken for the
    server itself. The discriminator is binary, so a ``servers`` map that
    itself looks like a server is read as one: rare, and it needs a
    malformed ``servers`` to trigger, but it hides the entries underneath
    rather than merely misfiling them.
    """
    if not isinstance(value, dict):
        return False
    return any(isinstance(value.get(field), kind) for field, kind in _OPENCODE_CONNECTION_FIELDS)


@dataclass(eq=False)
class OpenCodeConfigBlock(JsonConfigBlock):
    """``opencode.json`` or ``opencode.jsonc`` — OpenCode's project config.

    Read at the repository root and inside ``.opencode/``. The whole file is
    machine configuration, so it is a :class:`JsonConfigBlock` and never
    reaches a content rule; ``opencode-config-valid`` reads ``raw_data``.
    """

    category: str = "opencode-config"
    jsonc: ClassVar[bool] = True

    def tree_label(self) -> str:
        return f"{self.path.name} (OpenCode config)"


@dataclass(eq=False)
class OpenCodeMcpBlock(McpBlock):
    """The ``mcp`` section of an OpenCode project config.

    A second parser role on the same file as :class:`OpenCodeConfigBlock`,
    which is what puts OpenCode's MCP servers in front of the shared policy
    and security rules — ``mcp-prohibited`` finds it through
    ``find(McpBlock)`` like every other host's configuration.

    OpenCode's *shape* is its own: transports are named for where the server
    runs (``local``/``remote``) rather than for the wire protocol, a local
    server's ``command`` is an argv array rather than a string, and the
    environment map is spelled ``environment``. ``mcp-valid-json`` therefore
    stands aside from the shape checks for this block and
    ``opencode-config-valid`` performs them instead; the policy rules and the
    checks that do not depend on the dialect — a file that is not JSON, a
    ``url`` carrying user information, and the credentials in the maps
    declared by :attr:`credential_maps` below — still read this block where
    they read every other host's.
    """

    servers_key: ClassVar[str] = "mcp"
    # OpenCode's config has a documented top-level key for everything from
    # ``model`` to ``keybinds``. A document with no ``mcp`` key declares no
    # servers; reading the whole config as a server map would turn every
    # other setting into a server.
    allow_bare_server_map: ClassVar[bool] = False
    claude_builtins_reserved: ClassVar[bool] = False
    jsonc: ClassVar[bool] = True
    #: OpenCode spells the environment map ``environment`` and puts client
    #: credentials in ``oauth``. ``headers`` it spells like everyone else.
    credential_maps: ClassVar[Tuple[Tuple[str, bool], ...]] = (
        ("environment", False),
        ("headers", True),
        ("oauth", False),
    )
    credential_key_aliases: ClassVar[Mapping[str, str]] = MCP_OAUTH_V1_TO_V2

    def tree_label(self) -> str:
        return f"{self.path.name} (OpenCode MCP)"

    def server_entries(self) -> List[Tuple[str, Any]]:
        """Every declared server, under the v1 *and* the v2 layout.

        OpenCode 1.x maps names directly under ``mcp``; 2.0 nests them one
        level deeper under ``mcp.servers`` and still loads the 1.x form. A
        file mid-migration therefore carries both, and **both run** — so
        both are returned, nested first and then every flat sibling.

        Returning one layout or the other is a security hole rather than an
        approximation: server names are author-controlled, so a config that
        wraps one harmless server in ``servers`` and leaves a
        credential-bearing one flat beside it would hide the second from
        ``mcp-prohibited`` and from the credential scan — and from the one
        check ``mcp-valid-json`` keeps for this block, since that too reads
        this list.

        A name declared in both layouts appears twice. That is deliberate:
        they are two distinct objects that both ship, each can carry its own
        defect, and a mapping would keep only one. Upstream resolves the
        collision in favour of the 1.x value; skillsaw reports on both,
        because a credential in the losing copy is still committed.
        """
        data = self.raw_data
        if data is None:
            return []
        section = data.get(self.servers_key)
        if not isinstance(section, dict):
            return []
        nested = section.get("servers")
        # A v1 server may legitimately be called "servers", and a v2 server
        # may legitimately be called "command". Nothing forbids either name,
        # so the shape decides rather than the name.
        wrapper = isinstance(nested, dict) and not _is_opencode_server(nested)
        entries: List[Tuple[str, Any]] = list(nested.items()) if wrapper else []
        for name, cfg in section.items():
            if wrapper and name == "servers":
                continue
            # v2 carries a global ``timeout`` beside ``servers``. It is a
            # setting, not a server, and upstream skips it by name for
            # exactly this reason. A v1 server genuinely called ``timeout``
            # carries a connection field, so it survives the test.
            if name == "timeout" and not _is_opencode_server(cfg):
                continue
            entries.append((name, cfg))
        return entries


@dataclass(eq=False)
class CodexInlineMcpBlock(_InlineJsonPayload, McpBlock):
    """MCP servers written inline in a Codex ``.codex-plugin/plugin.json``."""

    inline_data: Optional[Dict[str, Any]] = None

    def tree_label(self) -> str:
        return f"{self.path.name} (inline mcpServers)"


@dataclass(eq=False)
class SettingsBlock(JsonConfigBlock):
    """settings.json or settings.local.json in .claude/."""

    category: str = "settings"

    @property
    def hooks_events(self) -> Dict[str, List[HookEventConfig]]:
        """Extract hooks, supporting both nested and flat formats.

        Nested (hooks.json style): { matcher, hooks: [{type, command}] }
        Flat (settings.json style): { type, command, matcher? }
        """
        data = self.raw_data
        if data is None:
            return {}
        return parse_hooks_events(data.get("hooks", {}))
