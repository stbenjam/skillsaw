## Why

`.cursor/hooks.json` runs shell commands around the agent loop — before a
shell command executes, before an MCP tool call, after a file edit. It ships
in the repository, so anyone who can land a commit can add one.

A key Cursor does not dispatch is ignored: the file loads, the hook never
fires, and nothing is reported. A hook meant to block dangerous shell
commands that is spelled `beforeShellExec` is not a hook at all, and the
failure looks identical to a hook that simply never triggered.

Cursor's event set grows — the 1.7 launch shipped six, and there are now
over twenty across agent, Tab, and application lifecycle. An unrecognised
name is therefore reported at `warning`, not `error`, and `extra-events`
lets a project accept an event newer than its skillsaw without waiting for
a release.

A hook entry is a command hook by default. A `type: "prompt"` hook asks the
model a question instead of spawning a process, and carries its text in
`prompt` rather than `command`.

This rule checks the shape. The commands themselves are scanned by
[`hooks-dangerous`](hooks-dangerous.md) and, when you want every hook
reviewed rather than only the risky-looking ones,
[`hooks-prohibited`](hooks-prohibited.md) — both read Cursor hooks through
the same path they use for Claude Code hooks and settings.

## Severity

Structural defects that stop a hook running are errors: a missing or
non-integer `version`, a missing `hooks` object, an event whose value is not
an array, an entry that is not an object, an unknown `type`, and a missing
or empty `command`/`prompt`.

Two checks are warnings, because the file still loads and the rest of it
still runs: an unrecognised event name, and an empty `hooks` object.

## Examples

**Bad** — a typo'd event that never fires, and a hook with nothing to run:

```json
{
  "version": 1,
  "hooks": {
    "beforeShellExec": [{ "command": "./scripts/audit.sh" }],
    "afterFileEdit": [{ "command": "" }]
  }
}
```

**Good** — a command hook and a prompt hook:

```json
{
  "version": 1,
  "hooks": {
    "beforeShellExecution": [
      { "command": "./scripts/audit-shell.sh" },
      { "type": "prompt", "prompt": "Does this command look safe?", "timeout": 10 }
    ],
    "afterFileEdit": [{ "command": "./scripts/format.sh" }]
  }
}
```

## How to fix

- Correct the event name to one Cursor dispatches. If Cursor added it after
  this skillsaw release, list it under the rule's `extra-events` setting:

  ```yaml
  rules:
    cursor-hooks-valid:
      extra-events:
        - afterSomethingNew
  ```

- Give every command hook a non-empty `command`: an absolute path, a path
  relative to `hooks.json`, or a shell snippet. Give every prompt hook a
  non-empty `prompt`.
- Set `"version": 1` — it is required, and `1` is the only value Cursor
  accepts today. Write it unquoted; `"1"` is a string.
