## Why

Codex runs lifecycle hooks from `<repo>/.codex/hooks.json` and from the
plugins a project installs — `hooks/hooks.json`, a file the manifest names
in `hooks`, or hooks written inline in `.codex-plugin/plugin.json`. They
ship in the repository, so anyone who can land a commit can add one.

Codex adopted Claude Code's nested shape — `{hooks: {Event: [{matcher?,
hooks: [{type, ...}]}]}}` — but not its vocabulary. Codex dispatches twelve
events; it runs `command` and `mcp_tool` handlers and *parses and skips*
`prompt` and `agent` ones. A hooks file copied from a Claude plugin
therefore loads without complaint and does less than it says: an event
Codex does not dispatch is skipped, and a `prompt` handler is read and
never run. Neither is reported by Codex.

This rule checks the shape against Codex's vocabulary. The commands
themselves are scanned by [`hooks-dangerous`](hooks-dangerous.md) and,
when you want every hook reviewed rather than only the risky-looking ones,
[`hooks-prohibited`](hooks-prohibited.md) — both read Codex hooks through
the same path they use for Claude Code hooks.

A hooks file that Claude Code also reads — the conventional
`hooks/hooks.json` of a plugin shipping both `.claude-plugin/` and
`.codex-plugin/` manifests — is checked by
[`claude-hooks-valid`](claude-hooks-valid.md) instead, so a dual-manifest
plugin keeps one set of results. A file that only the Codex manifest names
in `hooks`, and hooks written inline in that manifest, are read by nothing
else and are checked here.

These checks were part of `hooks-json-valid` before 0.20.0 split them out.
That legacy name resolves to
[`claude-hooks-valid`](claude-hooks-valid.md) only, so a project that had
`hooks-json-valid: {enabled: false}` must configure this rule by its own id.
Baselines are the exception: a finding recorded under the old name keeps
suppressing without a change.

## Severity

Structural defects that stop a hook running are errors: invalid JSON, a
document that is not an object, a missing or non-object `hooks`, an event
whose value is not an array, an entry that is not an object, a non-string
`matcher`, a missing `hooks` array, a handler that is not an object or has
no `type`, an unknown `type`, a missing or mistyped required field, a
mistyped optional field, and an `mcp_tool` handler on `SessionEnd`, which
does not support them.

A bare `NaN`, `Infinity` or `-Infinity` anywhere in the document is an
error too — including where nothing is typed, such as inside an `mcp_tool`
handler's `input`. None of those three is JSON, whatever a permissive
parser makes of them: Codex rejects the file and loads no hooks, so it is
reported once for the file rather than as a field's type.

Three checks are warnings, because the file still loads and the rest of it
still runs: an event name Codex does not dispatch, a `prompt` or `agent`
handler Codex parses and skips, and a field that belongs to the other
handler type. A `timeout` above three seconds on `SessionEnd` or
`Interrupt` is a warning too — Codex caps those events rather than
rejecting the file.

A `matcher` on an event that does not filter on one is `info`: harmless,
and worth knowing when you expected it to narrow the hook.

## Examples

**Bad** — a Claude event Codex never dispatches, and a handler type it
reads and skips:

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

**Good** — a command hook filtered by `matcher`, and an MCP tool hook:

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

- Correct the event name to one Codex dispatches. If Codex added it after
  this skillsaw release, list it under the rule's `extra-events` setting:

  ```yaml
  rules:
    codex-hooks-valid:
      extra-events:
        - SomethingNew
  ```

- Rewrite a `prompt` or `agent` handler as a `command` or `mcp_tool` one,
  or drop it — Codex will never run it as written.
- Give every `command` handler a `command` string, and every `mcp_tool`
  handler a `server` and a `tool`. Fields are per type: `commandWindows`,
  `additionalContextLimit` and `async` are command-only, `input` is
  `mcp_tool`-only.
- Move an `mcp_tool` handler off `SessionEnd`, which does not support them.
- Keep `SessionEnd` and `Interrupt` hooks under three seconds; Codex caps
  them there whatever `timeout` says.
