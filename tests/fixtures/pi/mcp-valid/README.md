# Pi MCP conformance fixtures

These cases were checked against Pi v0.99.2 on 2026-10-01 using the released
`loadMcpConfig` and `validateMcpServerConfig` functions, without connecting to
servers or executing credential commands.

- This fixture loads the `workspace` and `docs` servers with zero errors.
- The sibling `mcp-invalid` fixture loads only `dev-tools` and reports seven
  errors: the root toggle, SSE, argument type, project provider authentication,
  namespace collision, tool exposure, and OAuth callback-port type.

The sibling `mcp-overrides`, `mcp-client-registration`, and `mcp-bom`
fixtures were checked against Pi v1.5.0 on 2026-11-06 the same way, with a
global `mcp.json` defining the overridden servers. Pi reports exactly the
findings their tests expect; `notes` (`{}`) additionally fails there only when
no global server of that name exists.

The isolated source probe redirects the loader's imports to the release-tagged
validator and substitutes the public `.pi` directory constant. No validation
function is changed. Sources:

- [Configuration loader](https://github.com/earendil-works/pi/blob/v0.99.2/packages/coding-agent/src/extensions/mcp/config.ts)
- [Field validator](https://github.com/earendil-works/pi/blob/v0.99.2/packages/coding-agent/src/core/mcp-servers.ts)
