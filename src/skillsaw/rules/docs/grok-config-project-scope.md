## Why

Grok Build loads configuration across multiple layers, including personal user
configuration (`~/.grok/config.toml`) and repository project configuration
(`.grok/config.toml`).

The project configuration file is designed specifically for shared repository
settings: `[mcp_servers]`, `[permission]`, `[plugins]`, and `[mcp]
max_output_bytes`. Other settings (such as `[model]`, `[ui]`, `[tools]`,
`[telemetry]`, and user preferences) are intended for your personal user
configuration and are ignored when placed in `.grok/config.toml`.

Additionally, project hooks should be configured in `.grok/hooks/*.json`
rather than a `[hooks]` table in `config.toml`.

This rule helps ensure project configurations stay focused and effective by
identifying tables and settings that belong in user configuration or dedicated
hook files.

To validate the internal syntax and structure of the allowed tables, see
[`grok-config-valid`](grok-config-valid.md).

## Severity

Findings carry the rule's configured severity (**warning** by default):

**Settings intended for user configuration**

- Top-level tables or scalar values outside the supported project scope.
  Common user preferences like `[model]`, `[ui]`, `[tools]`, `[telemetry]`, and
  `disable_web_search` belong in your personal `~/.grok/config.toml`.
- `[hooks]` defined in `config.toml`: project hooks belong in
  `.grok/hooks/*.json`.
- `[plugins] paths`: local plugin development paths belong in your personal
  `~/.grok/config.toml`.

**Common table naming mismatches**

- `[[mcp.servers]]` or `[mcp.servers]` instead of `[mcp_servers.<name>]`.
- Hyphenated or camelCase spellings like `[mcp-servers.<name>]` or
  `[mcpServers.<name>]`.
- Plural `[permissions]` instead of `[permission]`.
- Using `transport` instead of `type` inside a server table.
- Using `defaultMode` inside `[permission]` (a Claude Code setting).

## What is not reported

- `[plugins] enabled` and `[plugins] disabled`, which are documented plugin
  switches.
- `[mcp] max_output_bytes`, which configures MCP message buffer limits.

## Examples

**Bad** — placing user settings and hooks inside project `.grok/config.toml`:

```toml
[mcp_servers.gateway]
command = "bin/gateway"

[model]
name = "grok-4"

[hooks]
SessionStart = [{ hooks = [{ type = "command", command = "make deps" }] }]
```

**Good** — keeping project configuration focused and moving hooks to `.grok/hooks/`:

```toml
# .grok/config.toml
[mcp_servers.gateway]
command = "bin/gateway"

[permission]
allow = ["Bash(make test)"]
```

```json
// .grok/hooks/deps.json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [{ "type": "command", "command": "make deps" }] }
    ]
  }
}
```

## How to fix

- Move personal preferences (such as default model, UI themes, and local plugin
  paths) into your personal `~/.grok/config.toml`.
- Configure project automation in `.grok/hooks/*.json` files and validate
  them with [`grok-hooks-valid`](grok-hooks-valid.md).
- Use `[mcp_servers.<name>]` for MCP servers and `[permission]` for tool
  permissions.

## Configuration

If a newer Grok Build release adds support for additional project-level tables,
you can accept them in `.skillsaw.yaml`:

```yaml
rules:
  grok-config-project-scope:
    extra-tables:
      - toolset
```
