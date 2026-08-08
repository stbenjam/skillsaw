## Why

MCP (Model Context Protocol) configuration files must be valid JSON with a
server map the host can actually read. Invalid JSON or the wrong structure
means no MCP servers load, and tools that depend on them silently fail.

## Which key, which file

The server map has two spellings, and each host reads exactly one:

| File | Key | Wrapper required? |
| --- | --- | --- |
| `.mcp.json`, plugin manifests | `mcpServers` | No — see below |
| `.cursor/mcp.json` | `mcpServers` | Yes |
| `.vscode/mcp.json` | `servers` | Yes |

A file using the other host's key is reported as such — the servers are
present but will not load. VS Code's documented siblings `inputs` and
`sandbox` are not servers and are left alone.

The Claude-family files accept a **wrapperless** map as well: a `.mcp.json`
whose top level is the server map itself, with no `mcpServers` key, is
valid and is not reported. Cursor and VS Code document one shape each and
have no such form, so a bare map there loads nothing and is reported.

```json
{"my-server": {"command": "node", "args": ["server.js"]}}
```

Transport is inferred when a server does not declare `type`: a `command`
means stdio, and a bare `url` means a remote server. Declaring `type`
explicitly overrides the inference, and an unknown value is reported.

## Examples

**Bad** — an unknown transport, which no host can connect over:

```json
{"mcpServers": {"my-server": {"type": "gopher", "command": "x"}}}
```

An empty `command` is a narrower case: the key is present, so the
presence-only check passes it in a Claude-family file. Only a Codex-only
plugin requires the value to name something spawnable.

**Good:**

```json
{
  "mcpServers": {
    "my-server": {
      "command": "npx",
      "args": ["my-server"]
    }
  }
}
```

## How to fix

Fix the JSON syntax error, or move the servers under the key this file's
host reads (see the table above). Each stdio server needs a `command` and
each remote server a `url`; when `type` is declared, the field must match
it.

Inside an OpenAI Codex-only plugin (Codex-claimed, with neither a
`.claude-plugin` marker nor a Claude marketplace listing — either one
counts as a Claude declaration), `command` and `url`
must also be **non-empty strings** — Codex resolves servers through the
manifest, and an empty value produces a server that silently never
starts. Plugins that ship both manifests are checked to the Claude
requirements, where presence alone satisfies the rule.

Avoid naming a server after one of Claude Code's built-in servers
(`workspace`, `claude-in-chrome`, `computer-use`, `Claude Preview`,
`Claude Browser`) — those names are reserved and a user server that
shadows one is ignored.
