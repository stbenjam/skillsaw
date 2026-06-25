## Why

`hooks.json` configures commands that run automatically on agent
events. Invalid JSON, unknown event types, or misconfigured handler
objects will cause hooks to fail silently — the command never runs
and no error is surfaced to the user.

## Examples

**Bad:**

```json
{
  "hooks": {
    "PostToolUse": {"command": "npm run lint"}
  }
}
```

**Good:**

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "hooks": [
          {"type": "command", "command": "npm run lint"}
        ]
      }
    ]
  }
}
```

## How to fix

Fix the structural issue identified in the violation message. Common
problems: event values must be arrays of config objects, each config
must have a `hooks` array, each handler needs a `type` field, and
type-specific fields (`command`, `url`, `prompt`) must match the
handler type.
