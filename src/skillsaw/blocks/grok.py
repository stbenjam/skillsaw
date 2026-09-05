"""Grok Build configuration discovered in a repository."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Mapping, Optional, Tuple

from skillsaw.formats.grok import PERMISSION_TABLE, mcp_transport
from skillsaw.formats.grok_mcp import normalized_mcp_server
from skillsaw.paths import safe_resolve

from .json_config import McpServerConfig, McpShapeDeferral
from .toml_config import TomlMcpConfigBlock


@dataclass(eq=False)
class GrokConfigBlock(TomlMcpConfigBlock):
    """A ``.grok/config.toml``, including user config in a HOME repository.

    It carries the MCP role because ``[mcp_servers.<name>]`` is where a Grok
    project declares its servers — there is no ``.grok/mcp.json`` — and the
    tables spell the fields the portable way, so ``mcp-prohibited`` reads
    them like any other host's. ``mcp-valid-json`` keeps only its
    dialect-neutral checks here; the document's shape is Grok's, not JSON's,
    and belongs to the Grok config rules.
    """

    #: The wrapper Grok reads. The file's other top-level tables are
    #: configuration rather than servers.
    servers_key: ClassVar[str] = "mcp_servers"

    #: The document is TOML and only its ``[mcp_servers]`` tables are
    #: servers, so the shared JSON shape walk has nothing to fall back to:
    #: it would report a config legitimately declaring only ``[permission]``.
    #: Unconditional for that reason, as Codex's is.
    shape_deferral: ClassVar[Optional[McpShapeDeferral]] = McpShapeDeferral(
        syntax_error_rule="grok-config-valid",
    )

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

    @property
    def is_user_config(self) -> bool:
        """Match the user file Grok excludes from project-layer discovery.

        A non-empty GROK_HOME is used verbatim; otherwise Grok uses the
        platform home directory. Canonical identity handles symlinked homes
        without inferring scope from a checkout's name or contents.
        """
        try:
            override = os.environ.get("GROK_HOME")
            home = Path(override) if override else Path.home() / ".grok"
            user_config = home / "config.toml"
            if self.path == user_config:
                return True
            resolved = safe_resolve(self.path)
            return resolved is not None and resolved == safe_resolve(user_config)
        except (OSError, RuntimeError, ValueError):
            return False

    @classmethod
    def transport(cls, server: Mapping[str, Any]) -> Optional[str]:
        """The transport Grok derives, which is not the portable default.

        The complete stdio variant is tried before HTTP; only fields in the
        selected variant are exposed. Invalid tables remain available from
        :meth:`server_entries` for config diagnostics.

        A server with ``enabled = false`` is kept. Grok omits it from
        ``inspect``, but the command it names is committed to the repository
        and a one-word edit turns it on, so the security scan reads it like
        any other.
        """
        return mcp_transport(server)

    @property
    def servers(self) -> List[McpServerConfig]:
        """Normalize aliases and omit fields ignored by the selected variant."""
        loaded = []
        for name, config in self.server_entries():
            if not isinstance(config, dict):
                continue
            transport = self.transport(config)
            if transport is not None:
                loaded.append(
                    McpServerConfig.from_dict(name, normalized_mcp_server(config, transport))
                )
        return loaded

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

    def tree_label(self) -> str:
        return "config.toml [grok]"
