"""Codex's project ``config.toml`` — the tree's second TOML node."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, List, Optional, Tuple

from skillsaw.formats.codex import CODEX_CONFIG_MCP_TABLE, codex_mcp_transport
from skillsaw.lint_target import LintTarget
from skillsaw.utils import read_toml

from .json_config import McpConfigRole, McpServerConfig, McpShapeDeferral


@dataclass(eq=False)
class CodexConfigBlock(McpConfigRole, LintTarget):
    """A ``.codex/config.toml`` — project-scoped Codex configuration.

    A direct :class:`~skillsaw.lint_target.LintTarget`, the way
    :class:`~skillsaw.blocks.grok.GrokConfigBlock` is: not a
    ``ContentBlock``, or every content rule would lint TOML as instruction
    prose, and not a ``JsonConfigBlock``, since that hierarchy parses JSON.

    Attached wherever Codex reads one, hooks or no hooks. It carries the MCP
    role because ``[mcp_servers.<name>]`` is where a Codex project declares
    its servers — there is no ``.codex/mcp.json`` — so ``mcp-prohibited``
    reads them through :meth:`~McpConfigRole.server_entries` with no
    knowledge of TOML, and ``mcp-valid-json`` keeps its dialect-neutral
    credential checks while deferring a shape walk written for JSON.

    The ``[hooks]`` tables hang under it as a
    :class:`~skillsaw.blocks.json_config.CodexConfigHooksBlock` child, so
    the hooks rules keep reading one ``HooksBlock`` hierarchy.

    Measured against codex-cli 0.153.0: both surfaces are live only once the
    developer's user config trusts the project directory, and both merge
    from every layer between the repository root and the session's cwd.
    """

    #: What the tree calls this node. Not a content category: nothing here
    #: is prose, so the context budget never counts it.
    category: str = "config"

    #: The table Codex reads. TOML has no bare-map form to fall back to, and
    #: the file's other top-level tables are settings rather than servers.
    servers_key: ClassVar[str] = CODEX_CONFIG_MCP_TABLE
    allow_bare_server_map: ClassVar[bool] = False

    #: Codex loads no Claude built-ins, so no name here shadows one.
    claude_builtins_reserved: ClassVar[bool] = False

    #: The document is TOML and only its ``[mcp_servers]`` tables are
    #: servers, so the shared JSON shape walk has nothing to fall back to:
    #: it would report a config legitimately declaring only ``[hooks]``.
    #: Unconditional for that reason, as Grok's is. The parse error belongs
    #: to ``codex-hooks-valid``, which reports it once for the whole file.
    shape_deferral: ClassVar[Optional[McpShapeDeferral]] = McpShapeDeferral(
        syntax_error_rule="codex-hooks-valid",
    )
    syntax_name: ClassVar[str] = "TOML"

    #: ``http_headers`` beside the inherited ``env``: Codex's spelling of the
    #: header map, and a literal token in one is committed to the repository.
    #: ``env_http_headers`` is deliberately absent — its values are the
    #: *names* of environment variables, which is the form that keeps a
    #: secret out of the file.
    credential_maps: ClassVar[Tuple[Tuple[str, bool], ...]] = (
        ("env", False),
        ("http_headers", True),
    )

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
    def servers(self) -> List[McpServerConfig]:
        """Every declared server, with the transport Codex derives.

        Overridden because the shared implementation defaults an absent
        ``type`` to stdio, and Codex has no ``type`` key at all: the
        transport follows from which connection field is present. A table
        naming neither is dropped, since there is nothing to model.

        Every *other* table is kept, including a server ``enabled = false``
        and one whose ``command`` sits beside a ``url`` — measured, that
        combination refuses the whole file, so nothing in it runs today. The
        commands are committed to the repository and a one-line edit makes
        them live, so hiding a sibling behind a malformed neighbour is not
        something the security scan should do.
        """
        loaded = []
        for name, config in self.server_entries():
            if not isinstance(config, dict):
                continue
            transport = codex_mcp_transport(config)
            if transport is None:
                continue
            server = McpServerConfig.from_dict(name, config)
            server.type = transport
            loaded.append(server)
        return loaded

    def tree_label(self) -> str:
        return "config.toml [codex]"
