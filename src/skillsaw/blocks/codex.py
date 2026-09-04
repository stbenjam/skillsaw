"""Codex's project ``config.toml``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Mapping, Optional, Tuple

from skillsaw.formats.codex import CODEX_CONFIG_MCP_TABLE, codex_mcp_transport

from .json_config import McpShapeDeferral
from .toml_config import TomlMcpConfigBlock


@dataclass(eq=False)
class CodexConfigBlock(TomlMcpConfigBlock):
    """A ``.codex/config.toml`` — project-scoped Codex configuration.

    Attached wherever Codex reads one, hooks or no hooks. It carries the MCP
    role because ``[mcp_servers.<name>]`` is where a Codex project declares
    its servers — there is no ``.codex/mcp.json`` — so ``mcp-prohibited``
    reads them like any other host's, and ``mcp-valid-json`` keeps its
    dialect-neutral credential checks while deferring a shape walk written
    for JSON.

    The ``[hooks]`` tables hang under it as a
    :class:`~skillsaw.blocks.json_config.CodexConfigHooksBlock` child, so
    the hooks rules keep reading one ``HooksBlock`` hierarchy.

    Measured against codex-cli 0.153.0: both surfaces are live only once the
    developer's user config trusts the project directory, and both merge
    from every layer between the repository root and the session's cwd.
    """

    #: The table Codex reads. The file's other top-level tables are settings.
    servers_key: ClassVar[str] = CODEX_CONFIG_MCP_TABLE

    #: The document is TOML and only its ``[mcp_servers]`` tables are
    #: servers, so the shared JSON shape walk has nothing to fall back to:
    #: it would report a config legitimately declaring only ``[hooks]``.
    #: Unconditional for that reason, as Grok's is. The parse error belongs
    #: to ``codex-hooks-valid``, which reports it once for the whole file.
    shape_deferral: ClassVar[Optional[McpShapeDeferral]] = McpShapeDeferral(
        syntax_error_rule="codex-hooks-valid",
    )

    #: ``http_headers`` beside the inherited ``env``: Codex's spelling of the
    #: header map, and a literal token in one is committed to the repository.
    #: ``env_http_headers`` and ``bearer_token_env_var`` are deliberately
    #: absent — their values are the *names* of environment variables, which
    #: is the form that keeps a secret out of the file.
    credential_maps: ClassVar[Tuple[Tuple[str, bool], ...]] = (
        ("env", False),
        ("http_headers", True),
    )

    # ``claude_builtins_reserved`` and ``require_usable_connection`` are
    # deliberately left at their inherited values: both are read only by the
    # JSON shape walk in ``mcp-valid-json``, which this block never reaches.
    # Setting them here would look like configuration and be dead.

    @classmethod
    def transport(cls, server: Mapping[str, Any]) -> Optional[str]:
        """Which connection key the table carries.

        Codex has no ``type`` key: the transport follows from ``command`` or
        ``url``, and a table naming neither is dropped.

        Every *other* table is kept, including a server ``enabled = false``
        and one whose ``command`` sits beside a ``url`` — measured, that
        combination refuses the whole file, so nothing in it runs. The
        commands are committed to the repository and a one-line edit makes
        them live, so hiding a sibling behind a malformed neighbour is not
        something the security scan should do.
        """
        return codex_mcp_transport(server)

    def tree_label(self) -> str:
        return "config.toml [codex]"
