"""The lint tree's TOML configuration nodes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Dict, List, Mapping, Optional, Tuple

from skillsaw.lint_target import LintTarget
from skillsaw.utils import read_toml

from .json_config import McpConfigRole, McpServerConfig


@dataclass(eq=False)
class TomlMcpConfigBlock(McpConfigRole, LintTarget):
    """A project ``config.toml`` whose ``[mcp_servers]`` tables are servers.

    A direct :class:`~skillsaw.lint_target.LintTarget`: not a
    ``ContentBlock``, or every content rule would lint TOML as instruction
    prose, and not a ``JsonConfigBlock``, since that hierarchy parses JSON.
    The MCP role is what the security and policy rules read, through
    :meth:`~McpConfigRole.server_entries`, with no knowledge of TOML.

    A file the parser refuses still gets a block, carrying
    :attr:`parse_error`, so the rule that reports it has something to report
    on.

    A subclass declares its host's :attr:`servers_key`, its
    :attr:`shape_deferral`, and :meth:`transport`; everything a host does not
    vary lives here.
    """

    #: What the tree calls this node. Not a content category: nothing here
    #: is prose, so the context budget never counts it.
    category: str = "config"

    #: TOML has no bare-map form to fall back to, and a config's other
    #: top-level tables are settings rather than servers.
    allow_bare_server_map: ClassVar[bool] = False
    syntax_name: ClassVar[str] = "TOML"

    _parsed: Optional[Tuple[Optional[dict], Optional[str]]] = field(
        default=None, init=False, repr=False
    )

    @classmethod
    def transport(cls, server: Mapping[str, Any]) -> Optional[str]:
        """The transport this host derives for one server table.

        ``None`` drops the table from :attr:`servers`. Abstract rather than
        defaulted: the shared implementation defaults an absent ``type`` to
        stdio, and neither TOML host has a ``type`` key at all.
        """
        raise NotImplementedError

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
        """Every declared server, with the transport the host derives.

        A table naming no transport is dropped, since there is nothing to
        model; it is still in :meth:`server_entries`, where the config rule
        finds it.
        """
        loaded = []
        for name, config in self.server_entries():
            if not isinstance(config, dict):
                continue
            transport = self.transport(config)
            if transport is None:
                continue
            server = McpServerConfig.from_dict(name, config)
            server.type = transport
            loaded.append(server)
        return loaded
