## Why

OpenAI Codex runs lifecycle hooks from `<repo>/.codex/hooks.json` and from
installed plugins — `hooks/hooks.json`, a custom path the manifest names, or
a payload written inline in `.codex-plugin/plugin.json`.

Codex adopted Claude Code's nested shape —
`{hooks: {Event: [{matcher?, hooks: [{type, ...}]}]}}` — and kept its own
vocabulary. It dispatches twelve lifecycle events, runs `command` and
`mcp_tool` handlers, and parses `prompt` and `agent` handlers without ever
running them. A file copied from a Claude plugin therefore loads without
complaint and does less than it says, with nothing on the console to
explain it.

The commands are a separate concern: [`hooks-dangerous`](hooks-dangerous.md)
scans them for risky execution patterns and
[`hooks-prohibited`](hooks-prohibited.md) checks them against an explicit
allowlist.

A plugin shipping both `.claude-plugin/` and `.codex-plugin/` manifests has
its shared `hooks/hooks.json` validated by
[`claude-hooks-valid`](claude-hooks-valid.md), so one file gets one set of
results. Dedicated Codex files and inline manifest hooks are checked here.

These checks were part of `hooks-json-valid` before 0.20.0 split them by
host. The legacy name resolves to
[`claude-hooks-valid`](claude-hooks-valid.md) for configuration and
suppression comments; baselines keep suppressing findings recorded under it.

## Severity

A finding's severity is how much of the file the defect costs.

**Errors** — Codex loads nothing, or a handler cannot run.

- *The whole file is skipped*: invalid JSON, a non-object root, a missing or
  non-object `hooks` key, or a non-finite number (`NaN`, `Infinity`,
  `-Infinity`) anywhere in the document.
- *The entry or handler is unusable*: an event whose value is not an array, a
  malformed matcher group, a handler with no `type` or an unrecognized one,
  or a handler missing a required field (`command` for command handlers,
  `server` and `tool` for MCP tool handlers).
- *The combination is not supported*: an `mcp_tool` handler on `SessionEnd`.

**Warnings** — the file loads and something in it does not fire.

- An event name Codex does not dispatch. The rest of the file still loads.
- A `prompt` or `agent` handler: parsed, never run.
- A field belonging to a different handler type, such as `commandWindows` on
  an MCP tool handler.
- A `timeout` above 3 seconds on `SessionEnd` or `Interrupt`, which Codex
  caps for these quick-exit events.

**Info** — a `matcher` on an event that does not filter on tool names. Codex
accepts it and ignores it.

## Examples

**Needs improvement** — an event Codex does not dispatch, and a prompt
handler it parses and skips:

```json
{
  "hooks": {
    "PostToolUseFailure": [
      { "hooks": [{ "type": "command", "command": "./scripts/report.sh" }] }
    ],
    "SessionStart": [
      { "hooks": [{ "type": "prompt", "prompt": "Summarise the repo" }] }
    ]
  }
}
```

**Good** — a command hook filtered by `matcher`, and a structured MCP tool
hook:

```json
{
  "description": "Repository policy hooks",
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "./scripts/audit-shell.sh",
            "timeout": 10,
            "statusMessage": "Auditing shell command"
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "hooks": [
          { "type": "mcp_tool", "server": "policy", "tool": "load_rules" }
        ]
      }
    ]
  }
}
```

## How to fix

- Use one of the twelve event names Codex dispatches.
- Rewrite `prompt` and `agent` handlers as `command` or `mcp_tool` handlers.
- Give every command handler a `command`, and every MCP tool handler both
  `server` and `tool`. Keep handler-specific fields with their type:
  `commandWindows`, `additionalContextLimit` and `async` belong to command
  handlers, `input` to MCP tools.
- Drop `mcp_tool` handlers from `SessionEnd`, which does not support them.
- Keep `SessionEnd` and `Interrupt` timeouts under 3 seconds.

Codex ships events faster than skillsaw releases. Rather than turning the
rule off, name a newer one:

```yaml
rules:
  codex-hooks-valid:
    extra-events:
      - SomethingNew
```
