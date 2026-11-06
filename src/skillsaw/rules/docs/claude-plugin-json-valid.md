## Why

`plugin.json` is the plugin manifest — if it contains invalid JSON or
is missing required fields, the plugin cannot be loaded. The host
application uses this file to register the plugin's name, version,
and capabilities.

`name` is required. `description`, `version`, and `author` are recommended;
their absence produces warnings controlled by `recommended-fields`.
When present, `version` must be a string. Claude Code accepts release labels
such as `"release-candidate"` and calendar versions such as `"2026.10"`
as well as semantic versions.

Component paths must resolve. A string path in `commands`, `agents`,
`skills`, `hooks`, `mcpServers`, `outputStyles` or `lspServers` that does
not exist, is absolute, or climbs out of the plugin with `..` fails to
load. An MCP server that reads `${user_config.KEY}` in its `command`,
`args`, `env`, `url` or `headers` needs `KEY` declared under the top-level
`userConfig`, or under the `userConfig` of a top-level `channels` entry
whose `server` names that server. Otherwise Claude Code cannot resolve it
on a fresh install and drops the server. A `${user_config.KEY}` in
`headersHelper` is never substituted, because the value would reach a
shell, so it is reported even when declared. The check reads the inline
`mcpServers` map, the plugin's `.mcp.json`, and any MCP file `mcpServers`
names by path. `claude plugin validate` makes the same checks; skillsaw repeats
them for CI runs and editors without Claude Code.

## Examples

**Bad:**

```json
{"name": "my-plugin", "version": 2026}
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
identified in the violation message. Write version values as JSON strings;
they do not need to follow semantic versioning. See the upstream
[manifest version reference](https://code.claude.com/docs/en/plugins-reference#version).
