## Why

MCP servers run as child processes with access to the local filesystem
and network. A project-scoped configuration that enables a
non-allowlisted MCP server can execute arbitrary code when a
contributor opens the repository — this is a supply-chain attack
vector analogous to malicious npm lifecycle scripts.

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
name (the key in `mcpServers`). This rule is disabled by default —
enable it for supply-chain-sensitive repositories.
