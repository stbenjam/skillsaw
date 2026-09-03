## Why

In Claude Code, `hooks.json` allows you to automate tasks and run helpful
commands in response to agent lifecycle events. Because hooks execute
automatically in the background, formatting mistakes, unexpected JSON values, or
misconfigured handlers can cause a hook to be skipped without surfacing an error
in the terminal. For example, non-standard numeric tokens like bare `NaN` or
`Infinity` will cause Claude Code's parser to reject the entire file.

This rule validates your Claude Code hook files to ensure event names, handler
types (`command`, `http`, `mcp_tool`, `prompt`, `agent`), and required options
are set up correctly.

Host-specific hook configurations for other tools are validated by their
dedicated rules:
- [`codex-hooks-valid`](codex-hooks-valid.md) for OpenAI Codex
- [`muse-hooks-valid`](muse-hooks-valid.md) for Muse Code
- [`cursor-hooks-valid`](cursor-hooks-valid.md) for Cursor

This rule was previously known as `hooks-json-valid` before host-specific checks
were introduced. The earlier rule name remains supported as an alias for backwards
compatibility, and a baseline recorded under it keeps applying here: this rule's
messages are unchanged from the ones it recorded.

The checks that moved to [`codex-hooks-valid`](codex-hooks-valid.md) were
re-worded, and a hooks file's baseline fingerprint hashes the message text —
JSON carries no line numbers to hash instead. An old baseline therefore carries
over to that rule only for the four file-level verdicts whose wording survived;
its page lists them.

For security, the commands themselves are scanned by
[`hooks-dangerous`](hooks-dangerous.md) for risky execution patterns, and can be
inventoried with an explicit allowlist using
[`hooks-prohibited`](hooks-prohibited.md).

## Examples

**Needs improvement** — hook handlers must be wrapped in a matcher group with a
`hooks` array:

```json
{
  "hooks": {
    "PostToolUse": {"command": "npm run lint"}
  }
}
```

**Good** — a properly structured matcher group and command handler:

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

Follow the suggestions in the finding message to address the structural issue:
- Event values should be arrays of matcher group objects.
- Each matcher group object requires a `hooks` array.
- Each handler inside `hooks` needs a valid `type` field.
- Type-specific fields (`command`, `url`, `prompt`, `server`/`tool`) should
  match the declared handler type.

