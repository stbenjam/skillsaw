## Why

`.muse/hooks.json` automates shell commands during Muse Code agent lifecycle
events — right before a tool runs, when a session starts, when the agent
finishes. The file is committed, so those commands are shared by everyone
working on the project.

Muse prints no diagnostic when it refuses something. A rejected file, a
dropped matcher group, a skipped event and a discarded handler all look
identical from the outside: a hook that had nothing to do. This rule reads
the file the way Muse's loader does, so the mistake shows up before the
silence does.

The commands themselves are a separate concern — they are scanned for risky
patterns by [`hooks-dangerous`](hooks-dangerous.md) and can be inventoried
against an explicit allowlist with
[`hooks-prohibited`](hooks-prohibited.md).

## Severity

A finding's severity is how much of the file the defect costs.

**Errors** — nothing runs, or one handler never does.

- *The whole file is skipped*: invalid JSON, a non-finite number (`NaN`,
  `Infinity`, `-Infinity`), an event value that is not an array, a matcher
  group that is not an object, a non-string `matcher`, a group missing its
  `hooks` array, a handler that is not an object, or a known handler field
  of the wrong type (`timeout: "10"`, `async: 1`). Muse refuses the document
  at parse time, so no hook in it runs.
- *The matcher group is dropped*: a key other than `matcher` and `hooks`.
  A `description` left over from a Claude Code hooks file costs that group;
  sibling groups and other events keep loading.
- *The handler is dropped*: a missing `type`, a type other than `command`,
  an empty `command`, an unrecognized key, or an option Muse parses and then
  refuses (`if`, `once: true`, `asyncRewake: true`). Other handlers in the
  same group still run.

**Warnings** — the file loads and something in it does not fire.

- An unrecognized event name. Event names are case-sensitive, so
  `sessionStart` matches nothing while correctly cased events keep running.
- `Setup`, which Muse recognizes from Claude Code's vocabulary and
  deliberately does not run.
- An empty `hooks` object, event array, or matcher-group `hooks` array —
  valid, and it configures nothing. (A matcher group with no `hooks` key at
  all is the error above, not this warning.)
- A `matcher` that does not compile. Muse compiles matchers with Rust's
  regex engine, which differs from Python's in both directions, so skillsaw
  checks both and warns rather than errors. Unicode classes, the
  character-class set operators, the `(?<name>...)` capture group and the
  `\z` anchor are Rust's spelling: skillsaw rewrites them rather than
  calling a working matcher broken. Look-around (`(?=`, `(?!`, `(?<=`,
  `(?<!`), backreferences (`\1`, `\k<name>`, `(?P=name)`) and the `\Z`
  anchor are the other direction — Python compiles them and Rust does not,
  so skillsaw names the construct instead of waiting for a compile error
  that never comes. The rest is the syntax the two dialects share. A matcher longer than 1,000
  characters is left alone: Muse sets no
  length limit, so length is not a defect, and a hooks file is untrusted
  input that the syntax check has no reason to scan without a bound.
- A handler with `commandWindows` and no `command`: it runs on Windows and
  does nothing on Linux or macOS.

**Info** — an event present in Muse's binary but not in its documented list
(`Notification`, `PostToolUseFailure`, `StopFailure`, `PostToolBatch`).
Verify it actually fires before relying on it.

An unknown key that appears in several groups or handlers — the usual shape
when a file is adapted from another tool — is reported once, listing where
it appears.

## Examples

**Bad** — an unexpected key drops the first matcher group, and an
unsupported Claude Code handler is dropped with it:

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

**Good** — matcher groups carrying only what Muse reads:

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

- Give each matcher group only `hooks` and, optionally, `matcher`. Notes
  belong in a companion Markdown file.
- Give every handler `"type": "command"` and a non-empty `command`. Keep a
  POSIX `command` beside any `commandWindows` so the hook runs everywhere.
- Adapting from Claude Code: fold `args` into the `command` string, set
  environment variables inside the script, and move conditional logic there
  too — Muse evaluates neither `if` nor `once: true`.
- Write `timeout` as a non-negative integer of seconds (`30`, not `30.0` or
  `"30"`).
- Match Muse's event names and their casing.

Muse adds events, handler fields and matcher-group keys faster than skillsaw
releases. Rather than turning the rule off, name the new one:

```yaml
rules:
  muse-hooks-valid:
    # An event name Muse dispatches that this release has not heard of.
    extra-events:
      - PreSomethingNew
    # A handler field Muse reads. Declared fields are accepted whatever they
    # hold — skillsaw has no type to check them against.
    extra-handler-fields:
      - retries
    # A matcher-group key beside `matcher` and `hooks`.
    extra-group-keys:
      - priority
```
