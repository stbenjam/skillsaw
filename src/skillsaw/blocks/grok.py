"""Grok Build's project ``config.toml``, the lint tree's only TOML node."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, List, Optional, Tuple

from skillsaw.formats.grok import PERMISSION_TABLE, mcp_transport
from skillsaw.lint_target import LintTarget
from skillsaw.utils import read_toml

from .json_config import McpConfigRole, McpServerConfig, McpShapeDeferral


@dataclass(eq=False)
class GrokConfigBlock(McpConfigRole, LintTarget):
    """A ``.grok/config.toml`` — project-scoped Grok Build configuration.

    A direct :class:`~skillsaw.lint_target.LintTarget`, the way
    :class:`~skillsaw.blocks.openai.OpenAIMetadataBlock` is: not a
    ``ContentBlock``, or every content rule would lint TOML as instruction
    prose, and not a ``JsonConfigBlock``, since that hierarchy parses JSON.

    It carries the MCP role because ``[mcp_servers.<name>]`` is where a Grok
    project declares its servers — there is no ``.grok/mcp.json`` — and the
    tables spell the fields the portable way, so ``mcp-prohibited`` reads
    them through :meth:`~McpConfigRole.server_entries` with no knowledge of
    TOML. ``mcp-valid-json`` keeps only its dialect-neutral checks here; the
    document's shape is Grok's, not JSON's, and belongs to the Grok config
    rules.

    A file the parser refuses still gets a block, carrying
    :attr:`parse_error`, so the rule that reports it has something to
    report on.
    """

    #: What the tree calls this node. Not a content category: nothing here
    #: is prose, so the context budget never counts it.
    category: str = "config"

    #: The wrapper Grok reads. TOML has no bare-map form to fall back to,
    #: and the file's other top-level tables are configuration rather than
    #: servers.
    servers_key: ClassVar[str] = "mcp_servers"
    allow_bare_server_map: ClassVar[bool] = False

    #: The document is TOML and only its ``[mcp_servers]`` tables are
    #: servers, so the shared JSON shape walk has nothing to fall back to:
    #: it would report a config legitimately declaring only ``[permission]``.
    #: Unconditional for that reason, where the other deferrals are gated on
    #: their format rule being able to run.
    shape_deferral: ClassVar[Optional[McpShapeDeferral]] = McpShapeDeferral(
        syntax_error_rule="grok-config-valid",
    )
    syntax_name: ClassVar[str] = "TOML"

    #: ``oauth`` beside the inherited ``env`` and ``headers``: Grok accepts
    #: it as a server field, and a table there can hold a literal secret the
    #: way OpenCode's can. Declared rather than reasoned about, because the
    #: shared scan skips a non-dict value, so a toggle costs nothing.
    credential_maps: ClassVar[Tuple[Tuple[str, bool], ...]] = (
        ("env", False),
        ("headers", True),
        ("oauth", False),
    )

    # ``claude_builtins_reserved`` and ``require_usable_connection`` are
    # deliberately left at their inherited values: both are read only by the
    # JSON shape walk in ``mcp-valid-json``, which this block never reaches.
    # Setting them here would look like configuration and be dead.

    _parsed: Optional[Tuple[Optional[dict], Optional[str]]] = field(
        default=None, init=False, repr=False
    )

    def _ensure_parsed(self) -> Tuple[Optional[dict], Optional[str]]:
        if self._parsed is None:
            self._parsed = read_toml(self.path)
        return self._parsed

    @property
    def raw_data(self) -> Optional[Dict[str, Any]]:
        data = self._ensure_parsed()[0]
        return data if isinstance(data, dict) else None

    @property
    def parse_error(self) -> Optional[str]:
        return self._ensure_parsed()[1]

    @property
    def permission(self) -> Optional[Dict[str, Any]]:
        """The parsed ``[permission]`` table, or ``None`` when absent.

        The other honored table, and the one Grok is silent about: every
        permission defect — a non-array ``allow``, an unparseable rule
        string, ``rules`` discarded because a list key sits beside it —
        produces no diagnostic at all.
        """
        data = self.raw_data
        if data is None:
            return None
        table = data.get(PERMISSION_TABLE)
        return table if isinstance(table, dict) else None

    @property
    def servers(self) -> List[McpServerConfig]:
        """Every server Grok loads, with the transport Grok derives.

        Overridden because the shared implementation defaults an absent
        ``type`` to stdio, and Grok does not: a non-empty ``command`` wins
        even beside a ``url``, a ``url`` alone is HTTP (or SSE when ``type``
        says so), and a table with neither is dropped outright. Dropping it
        here keeps the policy and security rules describing what actually
        runs; the table is still in :meth:`server_entries`, where the config
        rule finds it and reports it.

        A server with ``enabled = false`` is kept. Grok omits it from
        ``inspect``, but the command it names is committed to the
        repository and a one-word edit turns it on, so the security scan
        reads it like any other.
        """
        loaded = []
        for name, config in self.server_entries():
            if not isinstance(config, dict):
                continue
            transport = mcp_transport(config)
            if transport is None:
                continue
            server = McpServerConfig.from_dict(name, config)
            server.type = transport
            loaded.append(server)
        return loaded

    def tree_label(self) -> str:
        return "config.toml [grok]"
