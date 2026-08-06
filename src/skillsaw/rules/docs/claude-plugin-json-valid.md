## Why

`plugin.json` is the plugin manifest — if it contains invalid JSON or
is missing required fields, the plugin cannot be loaded. The host
application uses this file to register the plugin's name, version,
and capabilities.

## Examples

**Bad:**

```json
{"name": "my-plugin"}
```

**Good:**

```json
{
  "name": "my-plugin",
  "description": "Deployment automation plugin",
  "version": "1.0.0"
}
```

## How to fix

Fix the JSON syntax error or add the missing required fields
identified in the violation message. Required fields are `name`,
`description`, and `version`.
