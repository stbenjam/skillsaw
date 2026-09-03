## Why

`.muse/hooks.json` binds shell commands to Muse Code's lifecycle events —
before a tool runs, when a session starts, when the agent stops. It ships in
the repository, so anyone who can land a commit can add one.

Muse's loader reports nothing when it refuses one. In a headless run a
rejected file, a rejected matcher group, a skipped event and a dropped
handler all look identical to a hook that simply had nothing to do: no
diagnostic, no exit code, no log line. The only symptom is that the guard you
wrote never fires.

What a defect costs depends on where it is, and the message says which:

- **The whole file** — an event whose value is not an array, a matcher group
  that is not an object, a non-string group `matcher`, a group with a missing
  or non-array `hooks`, a handler that is not an object, any known handler
  field carrying the wrong JSON type, or a bare `NaN`, `Infinity` or
  `-Infinity` anywhere in the document — including where nothing is typed,
  such as `silent` or a member of `outputCapabilities`. None of those three
  is JSON, whatever a permissive parser makes of them. Muse refuses the
  document at parse time, so no hook in it runs.
- **That matcher group** — a group carrying any key beyond `matcher` and
  `hooks`, or a `matcher` that does not compile. A stray `"description"`
  copied from a Claude Code hooks file drops its own group; sibling groups
  and other events still load.
- **That event's entries** — a name Muse does not dispatch. Names are
  case-sensitive, so `sessionStart` configures nothing while the rest of the
  file loads.
- **That handler** — a missing or non-`command` `type`, a missing or empty
  `command`, a field Muse does not know, `if`/`condition`/`shell`/
  `rewakeMessage`/`rewakeSummary` with a string value, or `once: true` /
  `asyncRewake: true`. Sibling handlers in the same group still run.

Muse's handler fields are a subset of Claude Code's, so a hooks file copied
across from `.claude/` is the common way to get here: `args`, `env` and
`description` are fields Muse does not know, and `if`, `once` and
`asyncRewake` are ones it parses and then refuses the handler for.

This rule checks the shape. The commands themselves are scanned by
[`hooks-dangerous`](hooks-dangerous.md) and, when you want every hook
reviewed rather than only the risky-looking ones,
[`hooks-prohibited`](hooks-prohibited.md) — both read Muse hooks through the
same path they use for Claude Code hooks.

## Severity

Anything that stops a hook running is an error: an unparseable file, a
missing or non-object `hooks`, any of the whole-file shapes above, a stray
group key, an unknown or missing handler `type`, a missing or empty
`command`, an unsupported or unknown handler field, and a known field of the
wrong type (`timeout` must be a non-negative integer — a float, a numeric
string or a boolean all reject the file).

The softer checks are the ones where the file still loads and does something:

- an unrecognised event name, at `warning` — Muse adds events between
  skillsaw releases, and `extra-events` accepts one without waiting for a
  release;
- `Setup`, at `warning` — Muse recognises the Claude Code event by name and
  deliberately does not run it;
- an event Muse parses but does not document (`Notification`,
  `PostToolUseFailure`, `StopFailure`, `PostToolBatch`), at `info` — worth
  verifying before you rely on it;
- an empty `hooks` object, an event whose array is empty, or a group whose
  `hooks` array is empty, at `warning` — they configure nothing;
- a `matcher` that does not compile as a regex, at `warning` — Muse compiles
  matchers with Rust's `regex` crate, whose dialect is a superset of
  Python's, so patterns using Rust-only syntax are not reported at all;
- a handler with only `commandWindows`, at `warning` — it runs on Windows and
  does nothing anywhere else.

A stray key that repeats — the usual shape when a file is copied wholesale —
is reported once per key, naming the groups or handlers that carry it, rather
than once per occurrence.

## Examples

**Bad** — a group carrying a third key drops that group, and a handler copied
from Claude Code is dropped on its own:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "enabled": true,
        "hooks": [
          { "type": "command", "command": "./scripts/audit.sh", "args": ["--json"] }
        ]
      }
    ],
    "sessionStart": [
      { "hooks": [{ "type": "command", "command": "./scripts/bootstrap.sh" }] }
    ]
  }
}
```

**Good** — two keys per group, and every handler a command:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup",
        "hooks": [
          { "type": "command", "command": "./scripts/bootstrap.sh", "timeout": 30 }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "./scripts/audit.sh --json",
            "statusMessage": "Auditing command",
            "async": true
          }
        ]
      }
    ]
  }
}
```

## How to fix

- Give every matcher group `hooks` and, optionally, `matcher` — and nothing
  else. `matcher` is optional; omitted, empty and `"*"` all match everything.
  A `description` has nowhere to go in a Muse hooks file: JSON has no
  comments, so drop it or keep the note in the file that documents the hook.
- Give every handler `"type": "command"` and a non-empty `command` string.
  A handler that only has `commandWindows` needs a `command` too, or it does
  nothing on Linux and macOS.
- Replace Claude-only fields: fold `args` into the `command` string, export
  `env` from inside the script, and drop `description`. There is no
  replacement for `if`, `once` or `asyncRewake` — put the condition in the
  script and exit early. `once: false` and `asyncRewake: false` are accepted
  as written.
- Write `timeout` as a plain non-negative integer: `30`, not `30.0` and not
  `"30"`.
- Correct the event name to one Muse dispatches, matching case exactly. If
  Muse added it after this skillsaw release, list it under the rule's
  `extra-events` setting — and a handler field it added under
  `extra-handler-fields`:

  ```yaml
  rules:
    muse-hooks-valid:
      extra-events:
        - PreSomethingNew
      extra-handler-fields:
        - retries
  ```
