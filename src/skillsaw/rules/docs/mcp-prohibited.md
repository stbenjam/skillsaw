## Why

MCP servers run as child processes with access to the local filesystem
and network. A project-scoped configuration that enables a
non-allowlisted MCP server can execute arbitrary code when a
contributor opens the repository — this is a supply-chain attack
vector analogous to malicious npm lifecycle scripts.

The conventional MCP files are inventoried wherever the host that reads
them keeps one: `.mcp.json`, `.cursor/mcp.json`, `.vscode/mcp.json`, the
`mcp` section of an `opencode.json` or `opencode.jsonc`, and a plugin's
`mcp.json`. Servers
written inline in a manifest are covered too. OpenCode is inventoried in
both of its layouts — the 1.x map directly under `mcp` and the 2.0 one
under `mcp.servers` — including a file carrying both at once, since a
config could otherwise hide a server behind whichever layout went unread.
A Claude manifest that names its servers by *path* — `"mcpServers":
"./servers.json"` — is not followed, so that file is not inventoried. There
is no configuration that closes this: `content-paths` attaches a file as
prose for the content rules, which does not make it an MCP configuration.
Inline the servers in the manifest, or move them to a conventional
location, if you gate on this rule.

## Examples

**Bad (no allowlist configured):**

```json
{
  "mcpServers": {
    "unknown-server": {"command": "npx unknown-package"}
  }
}
```

**Good (with allowlist):**

```yaml
# .skillsaw.yml
rules:
  mcp-prohibited:
    allowlist:
      - "filesystem"
      - "github"
```

## How to fix

Review the flagged MCP server. If it is trusted, add its name to the
`allowlist` in your skillsaw config. Allowlist entries match by server
name — the key in the server map, which is `mcpServers` in `.mcp.json`,
`.cursor/mcp.json` and plugin manifests, and `servers` in
`.vscode/mcp.json`. This rule is disabled by default — enable it for
supply-chain-sensitive repositories.
