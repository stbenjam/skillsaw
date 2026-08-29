# Model Context Protocol (MCP) and MCP Registry

<!-- Repo-root-relative src/... and cross-reference paths below are intentionally kept as prose, not navigable links. -->
<!-- skillsaw-disable content-unlinked-internal-reference -->

This covers the MCP protocol spec and the MCP Registry publisher `server.json`
format. For MCP config *as embedded in Claude Code* (`.mcp.json`, `mcpServers`),
see also `references/claude.md`.

## Upstream source(s)
- Spec repo: https://github.com/modelcontextprotocol/modelcontextprotocol —
  "Specification and documentation for the Model Context Protocol" (hosted by the Linux
  Foundation).
- Rendered spec: https://modelcontextprotocol.io (and https://spec.modelcontextprotocol.io).
- Registry repo and documentation: https://github.com/modelcontextprotocol/registry.
- Versioned Registry schemas: https://static.modelcontextprotocol.io/schemas/,
  sourced from https://github.com/modelcontextprotocol/static/tree/main/schemas.

## What to check
- Transport types and their names (skillsaw validates against
  `VALID_MCP_TYPES = ("stdio", "http", "sse", "streamable-http", "ws")`).
- `mcpServers` object shape / required per-server fields.
- Any newly deprecated or added transports.
- Prohibited/dangerous server patterns skillsaw should flag.
- Newly published version directories under the Registry schema source. Compare their
  names with `MCP_REGISTRY_SCHEMA_VERSIONS` in
  `src/skillsaw/formats/mcp_registry.py`; each supported version must remain present
  in that registry and must resolve to its own immutable bundled schema.
- Registry `server.json` changes between every newly published schema and its
  predecessor: required fields, formats, package and transport enums, URL shapes,
  identifier constraints, JSON Schema dialect, local versus remote `$ref` targets,
  and other semantics enforced outside JSON Schema.

## skillsaw rules that map
Package `src/skillsaw/rules/builtin/mcp/`:
- `mcp-valid-json` — `mcp/valid_json.py`
- `mcp-prohibited` — `mcp/prohibited.py`

Package `src/skillsaw/rules/builtin/mcp_registry/`:
- `mcp-registry-server-json-valid` — `mcp_registry/server_json_valid.py`
- `mcp-registry-version-semver` — `mcp_registry/version_semver.py`
- `mcp-registry-npm-name-match` — `mcp_registry/npm_name_match.py`

## Sync notes
- `mcp/valid_json.py` hand-copies `VALID_MCP_TYPES` — re-check against the spec's current
  transport list (e.g. `sse` deprecation, `streamable-http` naming).
- Treat released Registry schemas as immutable. Never replace an existing bundle when
  upstream publishes another version. Add a new
  `src/skillsaw/schemas/mcp_registry/vYYYY_MM_DD/` package containing the schema copied
  byte-for-byte, its upstream license, and a `SCHEMA-SOURCE.md` that pins and links the
  exact source revision. Add that resource package to the package-data table in
  `pyproject.toml`, and verify the built wheel contains all three files.
- Add the new version and resource package to the supported-version registry in
  `src/skillsaw/formats/mcp_registry.py`. Keep every older entry so a document's
  canonical `$schema` URL selects the exact schema it declares. An unknown future
  version must receive one unsupported-version diagnostic; do not validate it using
  the newest known schema.
- Confirm the bundled schema's own `$schema` dialect is supported; validator selection
  is intentionally derived from that declaration rather than fixed to Draft 7. Audit
  every `$ref` before bundling. Validation must remain offline: retain local fragment
  references, or bundle referenced resources and configure local resolution rather
  than allowing `jsonschema` to retrieve a remote document.
- Diff each new schema against the prior version and review all three `mcp_registry/`
  rules for semantic changes that JSON Schema does not cover. Dispatch changed
  semantics by the parsed schema version rather than changing behavior globally, and
  add fixtures proving both the new behavior and retained behavior for every older
  supported version.
