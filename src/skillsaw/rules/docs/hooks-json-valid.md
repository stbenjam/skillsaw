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

Inside an OpenAI Codex-only plugin (a `.codex-plugin/plugin.json`
manifest with no Claude manifest alongside it), a `matcher` on a hook
config must be a **string** — Codex matches tool names against it as a
pattern, and a non-string value disables the hook without an error.
Plugins that ship both manifests are checked to the Claude
requirements, which leave `matcher`'s type unchecked.
