"""Handler for the ``skillsaw mcp`` subcommand."""

from __future__ import annotations

import importlib.util
import sys


def _run_mcp(args):
    # The MCP SDK is an optional extra (and needs Python >= 3.10, above
    # skillsaw's own floor) — fail with an actionable hint, not a traceback.
    if importlib.util.find_spec("mcp") is None:
        print(
            "Error: `skillsaw mcp` requires the optional 'mcp' dependency,"
            " which is not installed.",
            file=sys.stderr,
        )
        if sys.version_info < (3, 10):
            print(
                "The MCP SDK requires Python 3.10 or newer (you are running"
                f" {sys.version_info.major}.{sys.version_info.minor}).",
                file=sys.stderr,
            )
        else:
            print("Install it with: pip install 'skillsaw[mcp]'", file=sys.stderr)
        sys.exit(1)

    from ..mcp_server import create_server

    create_server().run(transport="stdio")
