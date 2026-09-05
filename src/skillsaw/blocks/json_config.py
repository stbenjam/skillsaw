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
from typing import (
    AbstractSet,
    Any,
    ClassVar,
    Dict,
    FrozenSet,
    Iterator,
    List,
    Mapping,
    Optional,
    Set,
    Tuple,
)

from skillsaw.formats import antigravity
from skillsaw.blocks.antigravity_mcp import read_mcp_config
from skillsaw.blocks.antigravity_hooks import read_hooks_config
from skillsaw.formats.opencode import MCP_OAUTH_V1_TO_V2
from skillsaw.formats.vscode import VSCODE_HOOK_COMMAND_FIELDS
from skillsaw.lint_target import LintTarget
from skillsaw.repository_types import RepositoryType
from skillsaw.utils import (
    commented_key_line,
    has_utf8_bom,
    read_text,
    read_json,
    read_json_strict,
    read_jsonc,
)


def _as_str(value: Any) -> Optional[str]:
    """*value* when it is a string, else ``None``."""
    return value if isinstance(value, str) else None


def _normalize_antigravity_handler_type(handler: "HookHandler") -> None:
    """Give an Antigravity handler with no ``type`` its default.

    ``agy`` treats an absent or empty ``type`` as ``command``. The shared
    security rules skip any handler whose type is not ``command``, so
    leaving it empty would silently exempt every hook written the short way
    — which is the way the vendor's own examples write them.
    """
    if not handler.type:
        handler.type = "command"


def _antigravity_entry_declares_a_handler(entry: Dict[str, Any]) -> bool:
    """Whether *entry* carries a handler of its own, beside any ``hooks``.

    A pure group — ``{"matcher": …, "hooks": […]}`` — declares no command
    at its own level, and rendering an empty handler for it would put a
    finding-less entry in front of every scanner.
    """
    return any(entry.get(field) is not None for field in antigravity.HOOK_HANDLER_COMMAND_KEYS)


def _as_str_list(value: Any) -> Optional[List[str]]:
    """*value* with non-string members filtered out, or ``None`` for non-lists.

    A bare string is not a list of arguments — iterating it would split
    the value into characters and scan each one.
    """
    if not isinstance(value, list):
        return None
    return [v for v in value if isinstance(v, str)]


#: Every key any host may carry an executable command string under. Each one
#: is a command something will run, so ``hooks-dangerous`` and
#: ``hooks-prohibited`` have to scan them all — a handler whose ``command``
#: is benign and whose Windows variant pipes a download into a shell is
#: exactly the shape this union exists to catch.
#:
#: Codex and Muse Code spell the Windows variant ``commandWindows``, and both
#: also accept ``command_windows``. This is deliberately a
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
    #: Fields that are this linter's own bookkeeping rather than anything
    #: a host reads, so a published document must not carry them.
    #: ``command_variants`` in particular defaults to ``[]`` rather than
    #: ``None``, so a "drop the empty ones" filter alone lets it through.
    #: Declared here so a new internal field is named beside the field
    #: itself rather than in ``docs/extractor.py``.
    INTERNAL_FIELDS: ClassVar[Tuple[str, ...]] = (
        "command_variants",
        "source_line",
        "type_line",
    )
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
    def from_dict(
        cls, d: Dict[str, Any], *, line_offset: int = 0, default_type: str = ""
    ) -> "HookHandler":
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
            type=_as_str(d.get("type", default_type)) or "",
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
    def from_dict(
        cls, d: Dict[str, Any], *, line_offset: int = 0, default_type: str = ""
    ) -> "HookEventConfig":
        handlers: List[HookHandler] = []
        raw_hooks = d.get("hooks", [])
        if isinstance(raw_hooks, list):
            for h in raw_hooks:
                if isinstance(h, dict):
                    handlers.append(
                        HookHandler.from_dict(h, line_offset=line_offset, default_type=default_type)
                    )
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


def parse_hooks_events(
    hooks_obj: Any, *, line_offset: int = 0, default_type: str = ""
) -> Dict[str, List[HookEventConfig]]:
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
                entries.append(
                    HookEventConfig.from_dict(
                        cfg, line_offset=line_offset, default_type=default_type
                    )
                )
            elif "type" in cfg or default_type:
                handler = HookHandler.from_dict(
                    cfg, line_offset=line_offset, default_type=default_type
                )
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
    path: Path,
    *,
    strict: bool = False,
    jsonc: bool = False,
    duplicate_keys_fatal: bool = True,
    merge_duplicate_fields: Tuple[Tuple[str, ...], ...] = (),
) -> Tuple[Optional[Any], Optional[str]]:
    if jsonc:
        # JSONC is always strict about the non-finite tokens; the locations
        # that opt into it are new surfaces with no shipped results.
        return read_jsonc(path, allow_duplicate_keys=not duplicate_keys_fatal)
    if not strict:
        return read_json(path)
    return read_json_strict(
        path,
        allow_duplicate_keys=not duplicate_keys_fatal,
        merge_duplicate_fields=merge_duplicate_fields,
    )


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
    #: Whether a repeated object key kills the file, asked where
    #: :attr:`strict_json` or :attr:`jsonc` is set. On by default, which is what every host
    #: measured before Antigravity does. Google's ``agy`` reads its
    #: ``hooks.json``, ``mcp_config.json`` and registries with Go's
    #: ``encoding/json``: the last value wins and the file loads, measured
    #: at all three nesting depths against 1.1.25, so the blocks it reads
    #: turn this off and keep the non-finite half, including registries
    #: written with JSONC comments and trailing commas.
    duplicate_keys_fatal: ClassVar[bool] = True
    merge_duplicate_fields: ClassVar[Tuple[Tuple[str, ...], ...]] = ()
    _parsed: Optional[Tuple[Optional[Any], Optional[str]]] = field(
        default=None, init=False, repr=False
    )

    def _ensure_parsed(self) -> None:
        if self._parsed is None:
            self._parsed = _parse_json_file(
                self.path,
                strict=self.strict_json,
                jsonc=self.jsonc,
                duplicate_keys_fatal=self.duplicate_keys_fatal,
                merge_duplicate_fields=self.merge_duplicate_fields,
            )

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

    def has_utf8_bom(self) -> bool:
        """Whether the file on disk opens with a UTF-8 byte-order mark.

        skillsaw reads with ``utf-8-sig``, which drops a BOM without a word,
        so the parsed document looks perfectly valid and every shape check
        passes. A host whose reader does not strip one sees ``\\ufeff{`` and
        refuses the file — verified for Grok Build 1.0.13, where ``grok
        inspect --json`` loads zero hooks from a BOM-prefixed file that is
        otherwise correct. So the answer belongs to the host: only a rule
        for one that is known to refuse it should ask.

        Three bytes off the front rather than the cached text, because the
        cache is exactly what already dropped the mark.
        """
        return has_utf8_bom(self.path)

    def first_non_finite(self) -> Optional[Tuple[str, float]]:
        """The first ``NaN``/``Infinity`` in this document, as ``(path, value)``.

        Two routes reach a value here, and a :attr:`strict_json` block is
        one of them. A block left at ``False`` parses the bare tokens
        ``json.loads`` accepts and no JSON host does, so it holds a
        document the tool it configures refuses. A block at ``True``
        rejects those tokens — but not ``1e400``, which is valid JSON that
        overflows to ``inf`` without ever passing through
        ``parse_constant``.

        So a rule reads this before its shape walk either way, and the
        finding names the file's real defect rather than a field's type.

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
    ``muse-hooks-valid`` :class:`MuseHooksBlock`, ``grok-hooks-valid``
    :class:`GrokHooksBlock`, and ``cursor-hooks-valid``
    :class:`CursorHooksBlock` — so a file is checked against the vocabulary
    of the tool that will actually load it. The tree builder picks the
    subclass from where the file lives and who claims the directory.

    :attr:`events` parses the nested shape Claude Code defined and Codex,
    Muse Code and Grok Build adopted: ``{hooks: {Event: [{matcher?, hooks: [{type,
    command, ...}]}]}}``. A host with a different shape overrides it
    (Cursor).
    """

    category: str = "hooks"
    #: The syntax this document is written in, named in a parse-error
    #: finding, the way :class:`McpConfigRole` names one. Announcing a TOML
    #: failure as invalid JSON would send the author to the wrong parser.
    syntax_name: ClassVar[str] = "JSON"
    #: What this syntax calls a key/value mapping and an ordered sequence,
    #: for the messages that name one. Declared beside :attr:`syntax_name`
    #: rather than branched on in the rule: a ``config.toml`` author never
    #: wrote a JSON object and has no way to write one. Bare nouns — the
    #: article is chosen where the message is built.
    mapping_noun: ClassVar[str] = "object"
    sequence_noun: ClassVar[str] = "array"

    @property
    def security_events(self) -> Dict[str, List[HookEventConfig]]:
        """Handlers exposed to the hook security and policy rules."""
        return self.events

    @property
    def effective_events(self) -> Dict[str, List[HookEventConfig]]:
        """Events to publish in documentation; hosts may narrow the scan view."""
        return self.events

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

    #: Handler fields this file must write as a non-negative whole number.
    #: Empty here: Codex refuses a ``hooks.json`` over a negative ``timeout``
    #: too, but the looser check is the one ``hooks-json-valid`` released,
    #: and tightening it would newly fail files that pass today.
    whole_number_fields: ClassVar[FrozenSet[str]] = frozenset()

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

    def has_utf8_bom(self) -> bool:
        """Never: this config has no file of its own.

        ``path`` is the manifest that carries the payload, so the base
        implementation would answer a question about a *different* document
        and report the inline hooks for a mark on the file around them.
        """
        return False

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
class CodexConfigHooksBlock(CodexHooksBlock):
    """The ``[hooks]`` tables of a ``.codex/config.toml``.

    Codex loads project hooks from two files and merges them, so a TOML-only
    project's hooks are live configuration. The payload is the document
    :func:`~skillsaw.formats.codex.codex_config_hooks` renders from the
    parsed TOML, which is why the block takes it by value rather than
    parsing: its parent :class:`~skillsaw.blocks.codex.CodexConfigBlock`
    reads the file once for the whole document.

    A ``HooksBlock`` deliberately, though the file is TOML: the hooks rules
    iterate that hierarchy and there is no hooks role to carry instead. See
    the block-hierarchy rule in the development instructions, which records
    the exception. Nothing JSON-shaped survives it —
    :meth:`first_non_finite` stands down and :attr:`syntax_name` names the
    parser that actually ran.

    The dangerous file of the two. Measured against codex-cli 0.153.2: a
    shape defect here — a syntax error, an event value that is not a
    sequence, a missing ``type`` or ``command``, a ``timeout`` or
    ``additionalContextLimit`` that is not a non-negative whole number, two
    spellings of one field, an unknown handler ``type`` — makes ``codex``
    exit 1 and refuse to start in the project at all, where the same defect
    in ``hooks.json`` is a warning that skips that one file.
    """

    #: The rendered hooks document, or ``None`` when the file did not parse.
    inline_data: Optional[Dict[str, Any]] = None
    #: What ``read_toml`` said when the file did not parse. Carried rather
    #: than re-derived so the whole file is read once, in the builder.
    toml_error: Optional[str] = None
    syntax_name: ClassVar[str] = "TOML"
    #: Both fields deserialize as unsigned: ``timeout`` a ``u64`` and
    #: ``additionalContextLimit`` a ``usize``. Measured, a negative in either
    #: exits 1 with ``invalid value: integer `-1```.
    whole_number_fields: ClassVar[FrozenSet[str]] = frozenset({"timeout", "additionalContextLimit"})
    mapping_noun: ClassVar[str] = "table"
    sequence_noun: ClassVar[str] = "array of tables"

    def _ensure_parsed(self) -> None:
        if self._parsed is None:
            self._parsed = (self.inline_data, self.toml_error)

    def first_non_finite(self) -> Optional[Tuple[str, float]]:
        """Never: the scan is about tokens JSON has no spelling for.

        ``json.loads`` accepts bare ``NaN``/``Infinity`` and no JSON host
        does, which is the defect the base implementation finds. TOML spells
        both natively (``nan``, ``inf``), so the parser reaches them and the
        document is not refused over the token. A ``timeout`` of ``nan`` is
        still a float where Codex wants a ``u64``, and the rule's field check
        reports it as the fatal defect it is.
        """
        return None

    def tree_label(self) -> str:
        return "[hooks]"


@dataclass(eq=False)
class GrokPluginHooksBlock(HooksBlock):
    """A hooks file a Grok plugin ships — its ``hooks/hooks.json``, or one
    the manifest names in ``hooks``.

    Deliberately a sibling of :class:`GrokHooksBlock` rather than a
    subclass. Grok loads plugin hooks through a different adapter from the
    project layer's, and in 1.0.13 that path publishes no observable at all:
    ``grok inspect --json`` reports one opaque entry for a plugin's hooks
    file whether the file is valid, empty or unparseable, so the failure
    scopes ``grok-hooks-valid`` reports were measured on ``.grok/hooks/*.json``
    and on that path only. Keeping the class separate is what keeps that
    rule off files its evidence does not cover.

    ``hooks-dangerous`` and ``hooks-prohibited`` read the shared
    :class:`HooksBlock` base, so the commands in here still reach them.
    """

    def tree_label(self) -> str:
        return f"{self.path.name} (grok plugin hooks)"


@dataclass(eq=False)
class GrokInlineHooksBlock(_InlineJsonPayload, GrokPluginHooksBlock):
    """Hooks written inline in a Grok ``.grok-plugin/plugin.json``.

    The manifest's ``hooks`` field takes a path or the object itself, and
    the binary logs "plugin hooks loaded from manifest inline" when it loads
    the object form. Same commands, so the same security rules — and the
    same unobservable per-entry scope as the file form, hence the same base.
    """

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

    @property
    def security_events(self) -> Dict[str, List[HookEventConfig]]:
        """Include prompt hooks in policy checks as well as command hooks."""
        events = self.events
        for event, _index, prompt in self.prompt_hooks():
            events.setdefault(event, []).append(
                HookEventConfig(handlers=[HookHandler(type="prompt", prompt=prompt)])
            )
        return events


@dataclass(eq=False)
class AntigravityHooksBlock(HooksBlock):
    """``<customization root>/hooks.json`` — Antigravity's lifecycle hooks.

    A map of *named* hooks rather than one ``hooks`` object:
    ``{name: {enabled?, Event: [...]}}``. ``PreToolUse`` and ``PostToolUse``
    hold ``{matcher, hooks: [handler, ...]}`` groups; ``PreInvocation``,
    ``PostInvocation``, ``Stop`` and ``SessionStart`` hold flat handler
    lists. A :class:`HooksBlock` so the security rules find it with every
    other host's file; the :attr:`events` override renders both shapes as
    the shared :class:`HookEventConfig` structure, so ``hooks-dangerous``
    and ``hooks-prohibited`` scan Antigravity hooks with no per-ecosystem
    branch. ``antigravity-hooks-valid`` reads ``raw_data`` for the shape
    itself.

    The security view applies three policies:

    * A top-level ``enabled`` is **not** a kill switch. Every top-level key
      is a hook *name*, so ``{"enabled": {"Stop": [...]}}`` is an ordinary
      hook that loads, and only a non-object value there is a hard parse
      error that drops the whole file — reading either as "hooks off" would
      hand any repository a one-word way to silence the command scanners.
    * A hook-level ``"enabled": false`` still exposes its handlers. The
      command is committed either way, and the one-word commit that arms it
      is not the diff a reviewer should first learn of it from. skillsaw
      reports what a repository ships, not what it currently runs.
    * The security rendering shows **both** readings of every entry — the
      entry's own handler and its nested ``hooks`` — rather than picking
      one from the event or from the payload. ``agy`` runs one of them, and
      which one turns on a single key; both commands are committed either
      way, and a scanner shown only the half this release believes runs
      misses the other on the next one-word edit. Picking by payload hides
      the ``command`` in ``{"Stop": [{"command": "…", "hooks": []}]}``;
      picking by event hides committed nested commands under a flat event.
    """

    category: str = "hooks"
    #: Measured: a bare ``NaN``/``Infinity`` token, a comment and a
    #: trailing comma each drop the whole file — ``failed to parse
    #: hooks.json … invalid character``, and the run loads zero named
    #: hooks.
    strict_json: ClassVar[bool] = True
    #: Repeated names/events replace earlier values, while handler strings
    #: retain their prior value on null. Earlier type errors still fail the file.
    duplicate_keys_fatal: ClassVar[bool] = False

    def _ensure_parsed(self) -> None:
        if self._parsed is None:
            self._parsed = read_hooks_config(self.path)

    def tree_label(self) -> str:
        return f"{self.path.name} (antigravity hooks)"

    @property
    def events(self) -> Dict[str, List[HookEventConfig]]:
        """Every command the file commits, for the security scanners.

        Both readings of every entry; see :meth:`effective_events` for the
        one ``agy`` actually dispatches.
        """
        return self._render_events(effective_only=False)

    @property
    def effective_events(self) -> Dict[str, List[HookEventConfig]]:
        """Only the reading ``agy`` dispatches, for ``skillsaw docs``.

        A published document says what the tool does, so it must not list a
        command the host discards. The event decides: a grouped event runs
        the nested ``hooks`` and ignores a stray top-level ``command``; a
        flat event runs the entry's own handler and ignores a ``hooks`` key.
        An event this release does not know — one a project declares
        through ``extra-events`` — has no binding to consult, so both
        readings stand.

        :attr:`events` keeps every command either way: the security rules
        report what a repository ships, and one key turns the other half
        on.
        """
        return self._render_events(effective_only=True)

    def _render_events(self, *, effective_only: bool) -> Dict[str, List[HookEventConfig]]:
        data = self.raw_data
        if not isinstance(data, dict):
            return {}
        result: Dict[str, List[HookEventConfig]] = {}
        for hook_spec in data.values():
            if not isinstance(hook_spec, dict):
                continue
            if effective_only and hook_spec.get("enabled") is False:
                continue
            for event_type, entries in hook_spec.items():
                if event_type in antigravity.HOOK_SPEC_NON_EVENT_KEYS:
                    continue
                if not isinstance(entries, list):
                    continue
                # ``agy`` binds event keys case-insensitively, so the file's
                # own spelling is normalized to the canonical name and two
                # spellings of one event land in the same bucket.
                canonical = antigravity.HOOK_EVENTS_BY_CASEFOLD.get(
                    antigravity.hook_key_fold(event_type) if isinstance(event_type, str) else "",
                    event_type,
                )
                configs: List[HookEventConfig] = []
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    # Scan both payloads; documentation follows the event's shape.
                    grouped = canonical in antigravity.TOOL_HOOK_EVENTS
                    flat = canonical in antigravity.FLAT_HOOK_EVENTS
                    show_nested = not (effective_only and flat)
                    show_own = not (effective_only and grouped)
                    if show_nested:
                        nested = HookEventConfig.from_dict(entry)
                        for handler in nested.handlers:
                            _normalize_antigravity_handler_type(handler)
                        if nested.handlers:
                            configs.append(nested)
                    if show_own and _antigravity_entry_declares_a_handler(entry):
                        handler = HookHandler.from_dict(entry)
                        _normalize_antigravity_handler_type(handler)
                        configs.append(HookEventConfig(handlers=[handler]))
                if configs:
                    result.setdefault(canonical, []).extend(configs)
        return result


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


@dataclass(frozen=True)
class McpShapeDeferral:
    """How ``mcp-valid-json`` stands its own shape walk down for one dialect.

    The shared walk reads a document the way the Claude family writes it.
    A host that spells MCP differently has a format rule of its own, and
    running both would report a correct file as invalid — so the block
    declares the deferral rather than the rule naming block classes.

    *repo_types* are the types gating that format rule — a set, because a
    host whose rule is gated on more than one (Antigravity's file appears
    both in a workspace and in a plugin) needs every one of them. The tree
    role is deliberately ``--type``-invariant while every format rule is
    ``repo_types``-gated, so a deferral conditioned on them falls back to
    the shared walk under a forced ``--type`` rather than leaving the file
    validated by nothing. Empty defers whatever ``--type`` says, for a
    document the shared walk cannot read at all — a fallback that reported
    a correct file would be worse than no fallback. A block that also
    names a :attr:`McpConfigRole.surface_rule` reaches that gate first, so
    for it the fallback is the one that gate describes, not this one.

    *keeps_dialect_neutral_checks* is False only where the owning rule
    already makes those findings itself.

    *syntax_error_rule* names the rule that reports "this file does not
    parse" for itself, so one defect gets one finding. ``None`` leaves that
    finding with ``mcp-valid-json``, where no ``version:`` pin can reach it;
    naming a rule falls back to the same place whenever a forced ``--type``
    gates that rule off *and* no ``surface_rule`` gate stood the walk down
    first.
    """

    repo_types: FrozenSet[RepositoryType] = frozenset()
    keeps_dialect_neutral_checks: bool = True
    syntax_error_rule: Optional[str] = None

    def applies(self, active_types: AbstractSet[RepositoryType]) -> bool:
        """Whether the owning rule can run under *active_types*.

        Empty :attr:`repo_types` always defers; otherwise the deferral
        holds only while at least one gating type is active, so a forced
        ``--type`` that switches the owning rule off returns the file to
        the shared walk.

        ``isdisjoint`` rather than an intersection: this is asked once per
        block, and building a set of the caller's types to throw away is
        the kind of allocation that adds up over a large repository.
        """
        return not self.repo_types or not self.repo_types.isdisjoint(active_types)


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
    #: Per-server keys whose *scalar* string value may hold a committed
    #: credential — Antigravity accepts ``clientSecret`` on the server
    #: itself, not only inside ``oauth``. Scanned by the same rules as a map
    #: value, so a placeholder is still a placeholder. Empty for a host that
    #: puts every credential in a map.
    credential_fields: ClassVar[Tuple[str, ...]] = ()
    #: Per-server keys holding the URL a remote server is reached at, read
    #: by the dialect-neutral user-information check ``mcp-valid-json``
    #: keeps for a block whose *shape* it defers. Declared on the block
    #: because the spelling is the host's: the Claude family writes ``url``
    #: and Antigravity writes ``serverUrl``. A host that spells it both
    #: ways lists both.
    connection_url_keys: ClassVar[Tuple[str, ...]] = ("url",)
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
    #: Whether another rule owns this document's shape; see
    #: :class:`McpShapeDeferral`. ``None`` — every Claude-family location —
    #: keeps the shared shape walk.
    shape_deferral: ClassVar[Optional[McpShapeDeferral]] = None
    #: The host rule gating shared shape and syntax checks at this location.
    #: Disabling it never disables credential checks or server policy.
    #: ``None`` leaves the shared shape walk unconditional.
    surface_rule: ClassVar[Optional[str]] = None
    #: The syntax this document is written in, named in a parse-error
    #: finding. Announcing a TOML failure as invalid JSON would send the
    #: author to the wrong parser.
    syntax_name: ClassVar[str] = "JSON"

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
            self._server_config(name, cfg)
            for name, cfg in self.server_entries()
            if isinstance(cfg, dict)
        ]

    def _server_config(self, name: str, cfg: Dict[str, Any]) -> McpServerConfig:
        """Read the portable shape; hosts override their endpoint semantics."""
        return McpServerConfig.from_dict(name, cfg)

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
    """Portable Agent Plugins ``mcp.json`` configuration.

    A closed, versioned schema with different defaults and failure
    boundaries, so ``agent-plugin-mcp-valid`` validates this file whole —
    including the checks no dialect changes — and ``mcp-valid-json`` stands
    down entirely rather than duplicating them.
    """

    shape_deferral: ClassVar[Optional[McpShapeDeferral]] = McpShapeDeferral(
        repo_types=frozenset({RepositoryType.AGENT_PLUGIN}),
        keeps_dialect_neutral_checks=False,
    )

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
class GrokMcpBlock(McpBlock):
    """A ``.mcp.json`` only Grok Build reads.

    A Grok-only plugin's conventional file, or one its manifest names in
    ``mcpServers``. A declared path is Grok's whatever else claims the
    directory, since only the Grok manifest names it. The conventional file
    is the exception: a dual-manifest directory keeps the shared
    :class:`McpBlock` the Claude or Codex branch attached, since two block
    classes over one file would report each of its servers twice.

    Claude's built-in server names are not reserved here — Claude reads
    neither a Grok-only plugin's conventional file nor a path only Grok's
    manifest names — and a connection field must be usable rather than
    merely present. The second is measured: a plugin ``.mcp.json``
    holding ``{"empty": {"command": ""}, "nourl": {"type": "http"},
    "good": {"command": "echo"}}`` lost ``nourl`` outright and loaded
    ``empty`` with an empty target, a server nothing can spawn. This is a
    new surface with no established results to preserve, so it requires the
    field from the start, as the editor locations do.
    """

    claude_builtins_reserved: ClassVar[bool] = False
    require_usable_connection: ClassVar[bool] = True
    #: Grok's parser refuses a bare ``NaN``/``Infinity`` token and a
    #: duplicated key — measured on a plugin manifest, which fails to load
    #: and takes the whole plugin with it. Only Grok reads this file, and it
    #: is a new surface with no established results to preserve.
    strict_json: ClassVar[bool] = True

    def tree_label(self) -> str:
        # The filename, not a fixed "mcp.json": a manifest may point
        # ``mcpServers`` at a file of its own naming, and the label has to
        # say which file a finding is about.
        return f"{self.path.name} (grok MCP)"


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


def _is_opencode_server(value: Any) -> bool:
    """Distinguish a direct MCP server from a map of named servers.

    Match OpenCode's ``isDirectServer`` compatibility discriminator: a
    present ``type`` or ``enabled`` whose value is not an object identifies
    a direct entry, including a bare v1 enabled toggle. Invalid scalar or
    array values still identify that entry so the shape rule reports the
    right server. Object-valued fields can instead be nested servers named
    ``type`` or ``enabled``.
    """
    if not isinstance(value, dict):
        return False
    return any(
        field in value and not isinstance(value[field], dict) for field in ("type", "enabled")
    )


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
    shape_deferral: ClassVar[Optional[McpShapeDeferral]] = McpShapeDeferral(
        repo_types=frozenset({RepositoryType.OPENCODE})
    )
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
            # v2 carries a global ``timeout`` beside ``servers``. A direct
            # server field, including an enabled toggle, identifies a v1
            # server genuinely called ``timeout`` rather than that setting.
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
class GrokInlineMcpBlock(_InlineJsonPayload, GrokMcpBlock):
    """MCP servers written inline in a Grok ``.grok-plugin/plugin.json``.

    Always Grok's, whatever else claims the directory: nothing but the Grok
    manifest carries this payload, so no other host loads it and no second
    block can exist for it.
    """

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
    surface_rule: ClassVar[Optional[str]] = "copilot-agent-valid"
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


@dataclass(eq=False)
class AntigravityMcpBlock(McpBlock):
    """``mcp_config.json`` — Antigravity's MCP servers.

    One per customization root and one per plugin. The *shape* is its own:
    a remote server is spelled ``serverUrl`` (which wins over ``command``
    when both are present), ``url`` plus ``type`` is a third accepted
    form, and a server with no connection field at all loads without
    complaint. ``mcp-valid-json`` therefore stands aside from the shape
    checks here and ``antigravity-mcp-valid`` performs them instead; the
    policy rules and the dialect-neutral checks — a ``url`` carrying user
    information, and the credentials in the maps :attr:`credential_maps`
    and the scalars :attr:`credential_fields` declare — still read this
    block where they read every other host's, including when
    ``antigravity-mcp-valid`` itself is gated off. The parse failure goes
    with the shape rather than with them: ``antigravity-mcp-valid`` owns
    it while it runs, and nothing reports it while that rule is off, so a
    user who pinned a ``version:`` past this release sees the results that
    release had.
    """

    #: A document with no ``mcpServers`` wrapper is silently ignored:
    #: ``agy`` loads no server from it and says nothing. Reading it as a
    #: bare server map would validate a file that does nothing.
    allow_bare_server_map: ClassVar[bool] = False
    claude_builtins_reserved: ClassVar[bool] = False
    #: Measured: a server with neither ``command`` nor ``serverUrl`` loads
    #: without any ``agy`` complaint, so "unusable connection" is not a
    #: defect this host has.
    require_usable_connection: ClassVar[bool] = False
    #: Measured: a comment or a trailing comma is exit 1, not a warning.
    strict_json: ClassVar[bool] = True
    #: Go accepts duplicate keys. Server fields also match without regard
    #: to case; the host-specific reader preserves their encounter order.
    duplicate_keys_fatal: ClassVar[bool] = False
    surface_rule: ClassVar[Optional[str]] = "antigravity-mcp-valid"
    credential_maps: ClassVar[Tuple[Tuple[str, bool], ...]] = antigravity.MCP_CREDENTIAL_MAPS
    #: Keep scanning tolerated top-level credential properties, although
    #: the host consumes those credentials only inside ``oauth``.
    credential_fields: ClassVar[Tuple[str, ...]] = antigravity.MCP_CREDENTIAL_FIELDS
    credential_key_aliases: ClassVar[Mapping[str, str]] = antigravity.MCP_CREDENTIAL_KEY_ALIASES
    #: ``serverUrl`` is Antigravity's spelling and wins over ``command``;
    #: ``url`` is a third accepted form. Both carry a credential when
    #: someone writes one into the authority, so both are scanned.
    connection_url_keys: ClassVar[Tuple[str, ...]] = ("serverUrl", "url")
    shape_deferral: ClassVar[Optional[McpShapeDeferral]] = McpShapeDeferral(
        repo_types=frozenset({RepositoryType.ANTIGRAVITY, RepositoryType.ANTIGRAVITY_PLUGIN}),
        syntax_error_rule="antigravity-mcp-valid",
        keeps_dialect_neutral_checks=True,
    )

    def _ensure_parsed(self) -> None:
        if self._parsed is None:
            self._parsed = read_mcp_config(self.path)

    def _server_config(self, name: str, cfg: Dict[str, Any]) -> McpServerConfig:
        """Apply Antigravity's endpoint precedence without changing other hosts."""
        server = super()._server_config(name, cfg)
        if cfg.get("serverUrl") not in (None, ""):
            server.url = cfg["serverUrl"]
            server.command = None
            server.args = None
        # Both URL spellings imply http unless the author names a type.
        # Unlike serverUrl, the portable url does not replace command/args.
        if server.url not in (None, "") and cfg.get("type") is None:
            server.type = "http"
        return server

    def tree_label(self) -> str:
        return f"{self.path.name} (antigravity MCP)"


@dataclass(eq=False)
class AntigravityConfigBlock(JsonConfigBlock):
    """An Antigravity registry file in a customization root.

    ``agents.json``, ``plugins.json``, ``skills.json`` or
    ``workflows.json`` — a ``customizations.JSONConfig`` document naming
    where else to load that kind of customization from, not the
    customizations themselves.
    """

    category: str = "antigravity config"
    jsonc: ClassVar[bool] = True
    #: Measured against a functional ``agents.json``: a repeated
    #: ``entries`` key and a repeated ``path`` inside one entry both load
    #: the last value's directory, with no diagnostic.
    duplicate_keys_fatal: ClassVar[bool] = False

    def tree_label(self) -> str:
        return f"{self.path.name} (antigravity config)"
