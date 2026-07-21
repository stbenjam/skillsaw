# Model Context Protocol (MCP)

<!-- Repo-root-relative src/... and cross-reference paths below are intentionally kept as prose, not navigable links. -->
<!-- skillsaw-disable content-unlinked-internal-reference -->

This covers the MCP protocol spec itself. For MCP config *as embedded in Claude Code*
(`.mcp.json`, `mcpServers`), see also `references/claude.md`.

## Upstream source(s)
- Spec repo: https://github.com/modelcontextprotocol/modelcontextprotocol —
  "Specification and documentation for the Model Context Protocol" (hosted by the Linux
  Foundation).
- Rendered spec: https://modelcontextprotocol.io (and https://spec.modelcontextprotocol.io).

## What to check
- Transport types and their names (skillsaw validates against
  `VALID_MCP_TYPES = ("stdio", "http", "sse", "streamable-http", "ws")`).
- `mcpServers` object shape / required per-server fields.
- Any newly deprecated or added transports.
- Prohibited/dangerous server patterns skillsaw should flag.

## skillsaw rules that map
Package `src/skillsaw/rules/builtin/mcp/`:
- `mcp-valid-json` — `mcp/valid_json.py`
- `mcp-prohibited` — `mcp/prohibited.py`

## Sync notes
- `mcp/valid_json.py` hand-copies `VALID_MCP_TYPES` — re-check against the spec's current
  transport list (e.g. `sse` deprecation, `streamable-http` naming).
