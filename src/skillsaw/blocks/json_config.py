"""Structured JSON configuration blocks: hooks, MCP, and settings.

These deliberately subclass :class:`LintTarget` (not ``ContentBlock``): they
are machine configuration, not prose for an agent's context window, so
content-quality rules never see them.  Dedicated rules locate them with
``find(HooksBlock)`` etc. and read ``raw_data``/``parse_error``.
"""

from __future__ import annotations

import math
from itertools import islice
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, ClassVar, Dict, Iterator, List, Mapping, Optional, Set, Tuple

from skillsaw.formats.opencode import MCP_OAUTH_V1_TO_V2
from skillsaw.lint_target import LintTarget
from skillsaw.utils import commented_key_line, read_text, read_json, read_json_strict, read_jsonc


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


#: VS Code's per-platform command keys, which ``copilot-agent-valid``
#: enforces as that host's vocabulary — one host's spelling, not the union.
VSCODE_HOOK_COMMAND_FIELDS = ("command", "windows", "linux", "osx")

#: Every key any host may carry an executable command string under. Each one
#: is a command something will run, so ``hooks-dangerous`` and
#: ``hooks-prohibited`` have to scan them all — a handler whose ``command``
#: is benign and whose Windows variant pipes a download into a shell is
#: exactly the shape this union exists to catch.
#:
#: Codex and Muse Code spell the Windows variant ``commandWindows``, and
#: Muse Code also accepts ``command_windows``. This is deliberately a
#: superset of every host's own vocabulary: it drives scanning only, never
#: validity — a shape rule reads its host's table in ``skillsaw.formats``.
HOOK_COMMAND_FIELDS = VSCODE_HOOK_COMMAND_FIELDS + ("commandWindows", "command_windows")


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
    source_line: Optional[int] = None
    # Keep new fields at the end to preserve positional construction.
    command_variants: List[Tuple[str, Optional[int]]] = field(default_factory=list)
    #: Line of the handler's ``type:`` key. ``source_line`` follows the
    #: ``command``, which an ``http``/``mcp_tool``/``prompt``/``agent``
    #: handler does not have — every finding about one was line-less until
    #: this, in YAML frontmatter that does carry line numbers. JSON-backed
    #: blocks have no lines to give and leave it ``None``, as they should.
    type_line: Optional[int] = None

    def iter_effective_commands(self) -> Iterator[Tuple[str, Optional[int]]]:
        """Yield each effective command and the line that declared it.

        Exec-form hooks store their executable and arguments separately.  The
        joined form is the linter's canonical spelling for scanning,
        diagnostics, and exact-match allowlists; it is not shell serialization.
        """
        variants = self.command_variants
        if not variants and self.command:
            variants = [(self.command, self.source_line)]
        for command, source_line in variants:
            if not command:
                continue
            if self.args is None:
                yield command, source_line
            else:
                yield " ".join([command, *self.args]), source_line

    @classmethod
    def from_dict(cls, d: Dict[str, Any], *, line_offset: int = 0) -> "HookHandler":
        """Build a handler from raw JSON, dropping values of the wrong type.

        The annotations here are a contract the JSON cannot be trusted to
        honour: ``{"type": "command", "command": ["curl", "..."]}`` is
        syntactically fine, and every consumer that joins or regex-scans
        ``command`` as a string raises ``TypeError`` on it. In
        ``hooks-dangerous`` that becomes a rule crash, which stops the scan
        before it reaches later blocks — so one malformed handler can hide
        a real ``curl | sh`` behind it. Dropping the value here leaves the
        field falsy, which every consumer already handles, and the host's
        own shape rule reads the raw document and reports it.
        """
        command_line = commented_key_line(d, "command")
        type_line = commented_key_line(d, "type")
        command_variants: List[Tuple[str, Optional[int]]] = []
        for key in HOOK_COMMAND_FIELDS:
            value = _as_str(d.get(key))
            if value is None:
                continue
            variant_line = commented_key_line(d, key)
            command_variants.append(
                (value, variant_line + line_offset if variant_line is not None else None)
            )
        return cls(
            type=_as_str(d.get("type")) or "",
            command=_as_str(d.get("command")),
            command_variants=command_variants,
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
            source_line=command_line + line_offset if command_line is not None else None,
            type_line=type_line + line_offset if type_line is not None else None,
        )


@dataclass
class HookEventConfig:
    """A single event config entry (matcher + handlers)."""

    matcher: str = ".*"
    handlers: List[HookHandler] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: Dict[str, Any], *, line_offset: int = 0) -> "HookEventConfig":
        handlers: List[HookHandler] = []
        raw_hooks = d.get("hooks", [])
        if isinstance(raw_hooks, list):
            for h in raw_hooks:
                if isinstance(h, dict):
                    handlers.append(HookHandler.from_dict(h, line_offset=line_offset))
        return cls(
            # Coerced like the handler fields: a list-valued matcher reaches
            # every consumer annotated ``str``, and the generated docs page
            # lowercases it while searching, which kills search for the
            # whole page. Codex uses the default when the field is absent,
            # and an invalid value is no more specific than absent.
            # codex-hooks-valid reports it, so coercing hides nothing.
            matcher=_as_str(d.get("matcher")) or ".*",
            handlers=handlers,
        )


def parse_hooks_events(hooks_obj: Any, *, line_offset: int = 0) -> Dict[str, List[HookEventConfig]]:
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
                entries.append(HookEventConfig.from_dict(cfg, line_offset=line_offset))
            elif "type" in cfg:
                handler = HookHandler.from_dict(cfg, line_offset=line_offset)
                matcher = _as_str(cfg.get("matcher")) or ".*"
                entries.append(HookEventConfig(matcher=matcher, handlers=[handler]))
        if entries:
            result[event_type] = entries
    return result


def json_token(value: float) -> str:
    """The JSON-source spelling of a non-finite float.

    ``repr`` renders these as ``nan`` and ``inf``, which appear nowhere in
    the file the author has to edit.
    """
    if math.isnan(value):
        return "NaN"
    return "Infinity" if value > 0 else "-Infinity"


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

    def first_non_finite(self) -> Optional[Tuple[str, float]]:
        """The first ``NaN``/``Infinity`` in this document, as ``(path, value)``.

        Only a block left at :attr:`strict_json` ``False`` can have one:
        ``json.loads`` accepts the bare tokens and no JSON host does, so a
        lenient block parses a document the tool it configures refuses. A
        rule that reads such a block asks here, before its shape walk, so
        the finding names the file's real defect rather than a field's type.

        Document order, iteratively: a document nested deeply enough to
        parse but deep enough to exhaust the recursion limit on a second
        walk would cost every other finding in the run.
        """
        stack: List[Tuple[str, Any]] = [("", self.raw_data)]
        while stack:
            path, value = stack.pop()
            if isinstance(value, float):
                if not math.isfinite(value):
                    return path, value
            elif isinstance(value, dict):
                for key, item in reversed(list(value.items())):
                    name = str(key)
                    stack.append((f"{path}.{name}" if path else name, item))
            elif isinstance(value, list):
                for index in range(len(value) - 1, -1, -1):
                    stack.append((f"{path}[{index}]", value[index]))
        return None

    def tree_label(self) -> str:
        return f"{self.path.name} ({self.category})"


@dataclass(eq=False)
class McpRegistryServerBlock(JsonConfigBlock):
    """Publisher metadata for one MCP Registry server."""

    category: str = "mcp registry"
    strict_json: ClassVar[bool] = True

    def tree_label(self) -> str:
        return "server.json (MCP Registry)"


@dataclass(eq=False)
class McpRegistryNpmPackageBlock(JsonConfigBlock):
    """Local npm ownership metadata referenced by Registry publisher data."""

    category: str = "mcp registry npm package"
    strict_json: ClassVar[bool] = True

    def tree_label(self) -> str:
        return "package.json (MCP Registry npm package)"


@dataclass(eq=False)
class HooksBlock(JsonConfigBlock):
    """A lifecycle-hooks document, whichever host reads it.

    The shared base for every hooks file in the tree. The security rules
    (``hooks-dangerous``, ``hooks-prohibited``) find every hooks file
    through this class and read :attr:`events`, which renders the document
    as :class:`HookEventConfig` entries whatever the host's shape.

    Shape validation is per host, because each host has its own event
    list, handler types, and fields: ``claude-hooks-valid`` iterates
    :class:`ClaudeHooksBlock`, ``codex-hooks-valid`` :class:`CodexHooksBlock`,
    ``muse-hooks-valid`` :class:`MuseHooksBlock`, and ``cursor-hooks-valid``
    :class:`CursorHooksBlock` — so a file is checked against the vocabulary
    of the tool that will actually load it. The tree builder picks the
    subclass from where the file lives and who claims the directory.

    :attr:`events` parses the nested shape Claude Code defined and Codex and
    Muse Code adopted: ``{hooks: {Event: [{matcher?, hooks: [{type,
    command, ...}]}]}}``. A host with a different shape overrides it
    (Cursor).
    """

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


@dataclass(eq=False)
class ClaudeHooksBlock(HooksBlock):
    """``hooks/hooks.json`` in a Claude Code plugin, or APM's compiled copy.

    Also the block a dual-manifest (Claude + Codex) plugin's hooks file
    gets: both hosts read it, and its established results are Claude's.
    """


@dataclass(eq=False)
class CodexHooksBlock(HooksBlock):
    """A hooks file only Codex reads.

    ``<repo>/.codex/hooks.json``, a Codex-only plugin's ``hooks/hooks.json``,
    or a file that plugin's manifest names in ``hooks``. Same nested shape as
    Claude's, with Codex's own events, handler types, and fields.
    """

    def tree_label(self) -> str:
        return f"{self.path.name} (codex hooks)"


@dataclass(eq=False)
class MuseHooksBlock(HooksBlock):
    """``.muse/hooks.json`` — Muse Code's committed project hooks.

    Same nested shape as Claude's. Muse's loader is strict about the shapes
    it reads — a handler carrying any field Muse does not know is dropped
    without a diagnostic in a headless run — which is what
    ``muse-hooks-valid`` exists to report.

    Lenient JSON parsing, deliberately. Muse reads the file with
    ``serde_json``, which accepts a duplicate key and takes the last value,
    and runs the file. A strict parser would refuse it, leave a
    ``parse_error``, and ``hooks-dangerous`` and ``hooks-prohibited`` skip a
    block that has one — so a second ``"hooks"`` key hiding a ``curl | sh``
    would evade both security rules on a file Muse happily executes.
    """

    def tree_label(self) -> str:
        return f"{self.path.name} (muse hooks)"


@dataclass(eq=False)
class GrokHooksBlock(HooksBlock):
    """One file from ``.grok/hooks/`` — Grok Build's committed project hooks.

    Grok reads that directory as a flat ``*.json`` glob and merges every
    file, so a repository has as many of these blocks as it has files. The
    label carries the filename for that reason: "hooks.json" alone would not
    say which of them a finding is about.

    Same nested shape as Claude's, with Grok's own events, alias table and
    handler fields. Its loader refuses a whole file over one wrong-typed
    field and reports nothing when it does, which is what
    ``grok-hooks-valid`` exists to say.

    Lenient JSON parsing, deliberately, for the reason
    :class:`MuseHooksBlock` documents: Grok reads the file with
    ``serde_json``, which takes the last of two duplicate keys and runs it,
    and both security rules skip a block carrying a ``parse_error``.
    """

    def tree_label(self) -> str:
        return f"{self.path.name} (grok hooks)"


def _inline_payload_token_count(data: Any) -> int:
    """Estimate tokens for an inline payload with bounded graph traversal.

    YAML aliases preserve object identity. Serializing an acyclic doubling
    alias graph expands it exponentially, while recursive aliases fail only
    after the serializer has already walked substantial hostile input. Count
    each container once and cap scheduled nodes instead; token estimates are
    advisory, so bounded and source-shape-proportional is the honest contract.
    """
    max_nodes = 10_000
    pending = [data if data is not None else {}]
    seen_containers: Set[int] = set()
    characters = 0
    visited = 0

    while pending and visited < max_nodes:
        value = pending.pop()
        visited += 1
        if isinstance(value, str):
            characters += len(value) + 2
        elif value is None:
            characters += 4
        elif isinstance(value, bool):
            characters += 4 if value else 5
        elif isinstance(value, (int, float)):
            characters += len(repr(value))
        elif isinstance(value, (dict, list, tuple, set, frozenset)):
            identity = id(value)
            if identity in seen_containers:
                # Approximate the compact alias/reference present in source.
                characters += 1
                continue
            seen_containers.add(identity)
            available = max_nodes - visited - len(pending)
            characters += 2
            if isinstance(value, dict):
                item_count = min(len(value), max(available // 2, 0))
                characters += max(2 * item_count - 1, 0)
                for key, item in islice(value.items(), item_count):
                    pending.extend((key, item))
            else:
                item_count = min(len(value), max(available, 0))
                characters += max(item_count - 1, 0)
                pending.extend(islice(value, item_count))
        else:
            # Timestamps and other YAML scalars need only a stable shape cost;
            # calling str/repr could execute or allocate without a useful gain.
            characters += len(type(value).__name__) + 2

    return characters // 4


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
        return _inline_payload_token_count(self.inline_data)

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
class CodexInlineHooksBlock(_InlineJsonPayload, CodexHooksBlock):
    """Hooks written inline in a Codex ``.codex-plugin/plugin.json``."""

    inline_data: Optional[Dict[str, Any]] = None

    def tree_label(self) -> str:
        return f"{self.path.name} (inline hooks)"


@dataclass(eq=False)
class CursorHooksBlock(HooksBlock):
    """``.cursor/hooks.json`` — Cursor's agent-lifecycle hooks.

    Cursor's shape is flatter than Claude's: ``{version, hooks: {event:
    [{command | prompt, type?, matcher?, timeout?}]}}``. There is no
    per-event ``matcher`` wrapper, and ``type`` defaults to ``"command"``
    rather than being required. A :class:`HooksBlock` so the security
    rules find it with every other host's file; the :attr:`events` override
    renders the flatter shape as the shared :class:`HookEventConfig`
    structure, so ``hooks-dangerous`` and ``hooks-prohibited`` scan Cursor
    hooks with no per-ecosystem branch. ``cursor-hooks-valid`` reads
    ``raw_data`` for the shape itself.
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
                # A shared file — `.cursor/hooks.json` symlinked to the
                # Codex or Muse document — carries the nested
                # ``{matcher?, hooks: [...]}`` shape instead. Only the first
                # host to reach a shared file gets a block for it, so an
                # entry this class skipped would take its commands out of
                # reach of every security rule. Reading it with the shared
                # nested parser is shape-agnostic; ``cursor-hooks-valid``
                # still judges the format on its own terms.
                if isinstance(entry.get("hooks"), list):
                    nested = HookEventConfig.from_dict(entry)
                    if nested.handlers:
                        configs.append(nested)
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


class McpConfigRole:
    """Host-neutral interface shared by JSON and embedded-YAML MCP nodes."""

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
    #: Host-specific transport spellings normalized before the shared shape
    #: validator chooses the required connection field. GitHub Copilot calls
    #: a process-backed server ``local``; the portable MCP spelling is
    #: ``stdio``. Keeping the alias on the block lets the shared validator
    #: remain host-neutral.
    type_aliases: ClassVar[Mapping[str, str]] = MappingProxyType({})

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
        # JSON object keys are always strings, but YAML-backed roles can carry
        # a malformed scalar key. Policy rules sort this set, so normalize
        # defensively after the shape rule reports the non-string name.
        return {str(s.name) for s in self.servers}


@dataclass(eq=False)
class McpBlock(JsonConfigBlock, McpConfigRole):
    """JSON MCP configuration at a host-owned path or inline manifest field."""

    category: str = "mcp"


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
class SkillsLockBlock(JsonConfigBlock):
    """A project ``skills-lock.json`` written by Vercel's skills CLI."""

    category: str = "skills-lock"
    strict_json: ClassVar[bool] = True

    def tree_label(self) -> str:
        return "skills-lock.json (skills lockfile)"


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
        ``mcp-prohibited`` and from the checks ``mcp-valid-json`` keeps for
        this block. That rule keeps three — a file that is not JSON, a
        ``url`` carrying user information, and the credentials in the maps
        declared by :attr:`credential_maps` — and the last two read this
        list.

        A name declared in both layouts appears twice. That is deliberate:
        they are two distinct objects that both ship, each can carry its own
        defect, and a mapping would keep only one. Only one of the two is in
        effect and this module names no winner; skillsaw reports on both,
        because a credential in the inert copy is still committed.
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
class CopilotAgentMcpBlock(McpConfigRole, LintTarget):
    """``mcp-servers`` embedded in Copilot custom-agent frontmatter.

    This is a direct lint-tree target rather than a ``JsonConfigBlock``: its
    payload is line-preserving YAML, while :class:`McpConfigRole` supplies the
    host-neutral interface shared MCP rules consume.
    """

    category: str = "mcp"
    inline_data: Optional[Dict[str, Any]] = None
    source_line: Optional[int] = None
    allow_bare_server_map: ClassVar[bool] = False
    claude_builtins_reserved: ClassVar[bool] = False
    require_usable_connection: ClassVar[bool] = True
    type_aliases: ClassVar[Mapping[str, str]] = MappingProxyType({"local": "stdio"})

    @property
    def parse_error(self) -> None:
        return None

    @property
    def raw_data(self) -> Optional[Dict[str, Any]]:
        return self.inline_data if isinstance(self.inline_data, dict) else None

    def estimate_tokens(self) -> int:
        return _inline_payload_token_count(self.inline_data)

    def source_line_for(self, node: Any, key: Any) -> Optional[int]:
        """Translate a nested frontmatter key to its file-absolute line."""
        nested = commented_key_line(node, key)
        return nested + 1 if nested is not None else self.source_line

    def tree_label(self) -> str:
        return f"{self.path.name} (agent mcp-servers)"


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
