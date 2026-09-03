## Why

Google Antigravity uses dedicated JSON configuration files to register and configure
customizations:
- `skills.json`: Declares skills enabled, disabled, or imported from local or remote locations.
- `plugins.json`: Registers plugin bundles enabled or loaded into the workspace.
- `mcp_config.json`: Configures Model Context Protocol (MCP) servers available to the agent.

Syntax errors, malformed entries, or invalid schemas prevent Antigravity from loading
the declared skills, plugins, or tools.

## Examples

**Bad:**

```json
{
  "entries": "invalid-entries-type-must-be-array-or-object"
}
```

**Good:**

```json
{
  "entries": [
    "./skills/my-custom-skill",
    "./skills/another-skill"
  ],
  "disabled": [
    "unwanted-skill"
  ]
}
```

## How to fix

Ensure that:
- The file contains valid JSON and the root is an object.
- For `skills.json` and `plugins.json`, `entries` is a valid array or object of path references.
- For `mcp_config.json`, `mcpServers` is an object defining valid MCP server configs with executable commands and arguments.
- Any unrecognized fields or invalid types are corrected.
