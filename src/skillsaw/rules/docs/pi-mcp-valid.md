## Why

Pi 0.99.0 introduced first-party MCP servers in project `.pi/mcp.json`.
Invalid entries are reported and skipped while valid sibling servers remain
available. This opt-in rule checks the field contract in Pi 1.5.0.

## Checks

- The root is an object with an optional `mcpServers` object.
- `autoEnableCodemode` is a boolean.
- Server names use letters, digits, underscores, and hyphens. Names differing
  only by hyphens and underscores share a namespace and conflict.
- `command` selects stdio; `url` selects HTTP first when type is omitted.
  Explicit transport types are `stdio`, `http`, and `streamable-http`.
  Legacy `sse` is rejected.
- Arguments, environment values, headers, OAuth field types, callback ports,
  exposure values, timeout, description, and enabled flags match the host.
- `oauth.authServerMetadataUrl` is a string. Pi requires HTTPS, with HTTP
  allowed on `localhost`, `127.0.0.1`, and `[::1]`; URI semantics remain
  delegated to its WHATWG parser.
- `oauth.clientRegistration` is `auto`, `dcr`, or `cimd`, and `cimd` is not
  combined with `oauth.clientId` or `oauth.clientName`.
- An entry without `command`, `url`, or `type` overrides the global server of
  the same name and may set only `enabled`, `exposure`, and `toolExposure`.
  Whether that global server exists is outside the repository and unchecked.
- Provider `auth` is unavailable in project HTTP definitions. Pi also rejects
  a truthy `auth` on stdio entries retaining a `url` property.
- A UTF-8 BOM is accepted; Pi strips it before parsing.

Unknown fields and fields belonging to the unselected transport are ignored.
An empty command, an omitted server map, and duplicate keys with the last value
winning match Pi's parser behavior. URI parsing and OAuth callback URI semantics
remain with Pi's WHATWG URL parser.
Namespace collision checks therefore use stdio servers and ordinary ASCII DNS
HTTP URLs without callback or authorization metadata URIs. Other HTTP entries
do not reserve a namespace because Pi may reject an unchecked URI before it
reserves the name.

## How to fix

Use a command and argument array for a process server, or an HTTP URL for a
remote server. Replace SSE endpoints with the server's streamable HTTP endpoint.
Keep provider-authenticated servers in the user-level configuration. To
change a global server for one project, list only the override fields:

```json
{"mcpServers": {"internal-tools": {"enabled": false}}}
```

Remove `clientId` and `clientName` when using `"clientRegistration": "cimd"`,
or choose `dcr` to keep them.

```json
{
  "mcpServers": {
    "docs": {
      "url": "https://docs.example.com/mcp",
      "headers": {"Authorization": "${DOCS_TOKEN}"},
      "exposure": "codemode"
    }
  }
}
```

Enable the rule explicitly:

```yaml
rules:
  pi-mcp-valid:
    enabled: true
```

## Security and boundaries

Shared `mcp-valid-json` credential checks and configured MCP policy rules
continue to inspect these files while this rule is disabled. Environment,
header, and OAuth secret values support `${NAME}` references and whole-value
`!command` expressions. Skillsaw never executes those expressions; structured
tokens embedded inside them are still reported.

Discovery includes nested projects and respects exclusions and checkout
containment. User configuration, server connections, and extension-registered
servers are not loaded.

## Upstream reference

The release-tagged [configuration loader](https://github.com/earendil-works/pi/blob/v1.5.0/packages/coding-agent/src/extensions/mcp/config.ts)
and [field validator](https://github.com/earendil-works/pi/blob/v1.5.0/packages/coding-agent/src/core/mcp-servers.ts)
define the checked contract. See the [Pi MCP documentation](https://pi.dev/docs/latest/mcp).
