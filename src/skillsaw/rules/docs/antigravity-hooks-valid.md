## Why

`hooks.json` configures lifecycle hooks for Google Antigravity workspaces and plugins.
Hooks run commands or HTTP requests when specific agent lifecycle events occur (such as
`SessionStart`, `PreToolUse`, or `Stop`). Malformed hook configurations, missing handler types,
invalid event names, or wrong types can cause hooks to fail to execute or prevent the entire
hooks file from loading.

## Examples

**Bad:**

```json
{
  "hooks": {
    "UnknownEvent": [
      {
        "hooks": [
          { "command": "./test.sh" }
        ]
      }
    ]
  }
}
```

**Good:**

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "./scripts/audit.sh", "timeout": 10 }
        ]
      }
    ]
  }
}
```

## How to fix

Ensure that:
- The root of `hooks.json` contains a `hooks` object.
- Event names are valid lifecycle events (e.g. `SessionStart`, `PreToolUse`, `PostToolUse`, `Stop`, `UserPromptSubmit`).
- Each entry in an event list is a group containing a `hooks` array.
- Each handler specifies a `type` (`command` or `http`).
- `command` handlers include a `command` string.
- `http` handlers include a `url` string.
- `timeout` is a non-negative integer.
