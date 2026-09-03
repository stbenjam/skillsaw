## Why

A Claude Code `hooks.json` configures commands that run automatically on
agent events. Invalid JSON, unknown event types, or misconfigured handler
objects will cause hooks to fail silently — the command never runs and no
error is surfaced to the user.

The event names, the handler types (`command`, `http`, `mcp_tool`,
`prompt`, `agent`) and the per-handler fields checked here are Claude
Code's. Other hosts read the same nested shape with their own vocabulary,
so their files are validated by their own rules —
[`codex-hooks-valid`](codex-hooks-valid.md),
[`muse-hooks-valid`](muse-hooks-valid.md) and
[`cursor-hooks-valid`](cursor-hooks-valid.md) among them.

This rule was called `hooks-json-valid` before that split, and the old name
still works everywhere a rule is named — but it resolves to this rule alone.
If you had `hooks-json-valid: {enabled: false}` in a Codex project, that
setting no longer covers Codex's hooks: configure
[`codex-hooks-valid`](codex-hooks-valid.md) by its own id.

The commands themselves are scanned by
[`hooks-dangerous`](hooks-dangerous.md) and, when you want every hook
reviewed rather than only the risky-looking ones,
[`hooks-prohibited`](hooks-prohibited.md).

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
