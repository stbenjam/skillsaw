## Why

MCP (Model Context Protocol) configuration files must be valid JSON
with a proper `mcpServers` structure. Invalid JSON or missing
structure means no MCP servers will be loaded, and tools that depend
on them will silently fail.

## Examples

**Bad:**

```json
{"servers": {"my-server": {"command": "npx my-server"}}}
```

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

Fix the JSON syntax error or restructure the file to use the
`mcpServers` top-level key with properly configured server entries.
Each server needs at minimum a `command` field.
