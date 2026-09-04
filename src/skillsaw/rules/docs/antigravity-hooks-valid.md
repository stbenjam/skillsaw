## Why

`hooks.json` configures lifecycle hooks for Google Antigravity workspaces and plugins.
Hooks run shell commands when specific agent lifecycle events occur (such as
`PreToolUse`, `PostToolUse`, `PreInvocation`, `PostInvocation`, or `Stop`).
Malformed hook configurations, unknown lifecycle events, invalid handler fields, or
syntax errors prevent hooks from executing or cause Antigravity to fail to load the configuration.

## Examples

**Bad:**

```json
{
  "audit-logger": {
    "UnknownEvent": [
      {
        "command": "./scripts/audit.sh"
      }
    ]
  }
}
```

**Good:**

```json
{
  "audit-logger": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "command": "./scripts/audit.sh", "timeout": 10 }
        ]
      }
    ]
  },
  "test-hook": {
    "PreInvocation": [
      {
        "command": "echo test",
        "timeout": 10,
        "type": "command"
      }
    ]
  }
}
```

## How to fix

- Define a JSON object at the root of `hooks.json` containing hook groups keyed by hook name (e.g., `"audit-logger"`).
- Optionally specify `"enabled": true` or `"enabled": false` within each hook group.
- Use supported Antigravity lifecycle events:
  - Tool events: `PreToolUse`, `PostToolUse` (configured as arrays of matcher objects with `matcher` regex and `hooks` list of handlers).
  - Invocation/lifecycle events: `PreInvocation`, `PostInvocation`, `Stop` (configured as arrays of handler objects).
- If Antigravity added an event after this skillsaw release, permit it under the rule's `extra-events` setting:

  ```yaml
  rules:
    antigravity-hooks-valid:
      extra-events:
        - CustomLifecycleEvent
  ```

- Specify a `command` string, an optional `type` (`"command"`), and an optional positive number for `timeout` on each handler definition.
- Verify that regular expression patterns in `matcher` fields are valid regexes.
