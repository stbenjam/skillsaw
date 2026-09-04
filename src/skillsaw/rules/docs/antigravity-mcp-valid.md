## Why

Google Antigravity configures Model Context Protocol (MCP) servers via `mcp_config.json`
files located in `.agents/`, `.agent/`, or within Antigravity plugins. This rule validates
the structure and transport definitions in `mcp_config.json` to ensure Antigravity can
successfully establish connections to declared MCP servers.

The configuration requires an `mcpServers` JSON object mapping unique server names to their
server definitions. Each server definition uses one of two transport configurations:

- **stdio transport**: Local process servers require a `command` string, and optionally accept
  `args` (a list of string arguments) and `env` (a key-value object of environment variable strings).
- **remote transport**: Remote HTTP/SSE servers specify `serverUrl` (an endpoint URL string)
  and optionally accept `headers` (a key-value object of HTTP headers).

A missing `mcpServers` object, invalid server transports (e.g. missing both `command` and
`serverUrl`), invalid field types, or JSON syntax errors prevent Antigravity from initializing
the specified MCP servers.

## Examples

**Bad:**

A stdio server missing a `command`, and a server defined as a non-object:

```json
{
  "mcpServers": {
    "incomplete-stdio": {
      "args": ["run"]
    },
    "invalid-server": "not-an-object"
  }
}
```

**Good:**

Valid stdio and remote MCP server definitions:

```json
{
  "mcpServers": {
    "local-tools": {
      "command": "node",
      "args": ["./scripts/mcp-server.js"],
      "env": {
        "DEBUG": "false"
      }
    },
    "remote-tools": {
      "serverUrl": "https://mcp.example.com/sse",
      "headers": {
        "User-Agent": "Antigravity/1.0"
      }
    }
  }
}
```

## How to fix

- Define an `mcpServers` JSON object at the root of `mcp_config.json`.
- Key each server entry by a descriptive server name.
- For local process (stdio) servers, specify a non-empty `command` string, and optional `args` list of strings and `env` object.
- For remote servers, specify a valid `serverUrl` string, and optional `headers` key-value mapping.
- Avoid embedding sensitive credentials or authorization tokens in `env` or `headers`.
