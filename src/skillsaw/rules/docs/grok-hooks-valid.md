## Why

`.grok/hooks/*.json` automates shell commands and HTTP calls during Grok
Build agent lifecycle events — right before a tool runs, when a session
starts, when the agent finishes. The files are committed, so those commands
are shared by everyone working on the project.

Grok prints no diagnostic when it refuses something. A rejected file, a
dropped matcher group, a skipped event and a discarded handler all look
identical from the outside: a hook that had nothing to do. `grok inspect
--json` reports no configuration warning for any of them. This rule reads
each file the way Grok's loader does, so the mistake shows up before the
silence does.

Grok reads the directory as a flat `*.json` glob and merges every file in
it, so a finding names the file it belongs to. A file in a subdirectory, or
under any other extension, is never loaded at all.

The commands themselves are a separate concern — they are scanned for risky
patterns by [`hooks-dangerous`](hooks-dangerous.md) and can be inventoried
against an explicit allowlist with
[`hooks-prohibited`](hooks-prohibited.md).

## Severity

A finding's severity is how much of the file the defect costs.

**Errors** — nothing in the file runs. Grok reads it with a parser that
refuses the whole document rather than the offending part, so one mistake
here costs every hook in the file, including the ones under other events.

- Invalid JSON, or a non-finite number (`NaN`, `Infinity`, `-Infinity`),
  which Grok's parser does not accept.
- No top-level `hooks` object, or one that is not an object.
- An event whose value is not an array, a matcher group that is not an
  object, a group with no `hooks` key or a non-array one, or a handler that
  is not an object.
- A handler with no `type`. There is no default.
- A known field carrying the wrong JSON type: `type`, `command` and `url`
  are strings, `timeout` is a non-negative integer, and `env` is an object
  whose values are strings. `"timeout": "30"`, `30.0`, `-1` and `true` each
  cost the file. A large `timeout` is fine — `Stop` and `SubagentStop`
  default to 600 seconds because gates run test suites.

**Warnings** — the file loads and something in it does not fire.

- An unrecognized event name. Grok skips the entries under it so the rest of
  the file still loads, which is why a typo is invisible at runtime.
- A `matcher` that does not compile. Grok compiles matchers with Rust's
  regex engine, which differs from Python's at the edges (no lookarounds or
  backreferences, plus Unicode classes and set operators Python lacks), so
  skillsaw checks the syntax the two dialects share and warns rather than
  errors. A matcher longer than 1,000 characters is left alone: Grok sets no
  length limit, so length is not a defect, and a hooks file is untrusted
  input that the syntax check has no reason to scan without a bound.
- A `command` handler with no `command`, an `http` handler with no `url`, or
  a `type` other than `command` and `http`. Each drops that one handler;
  siblings in the same group still run.
- An empty `hooks` object or event array — valid, and it configures nothing.

**Info** — the file loads, the hook runs, and one thing in it is ignored.

- An `env` entry naming a variable the hook runner injects
  (`GROK_HOOK_EVENT`, `GROK_HOOK_NAME`, `GROK_SESSION_ID`,
  `GROK_WORKSPACE_ROOT`, `CLAUDE_PROJECT_DIR`). The runner's value always
  wins, so the declared one never reaches the process.
- A `matcher` on `Stop` or `UserPromptSubmit`. Those events always fire, so
  the pattern is kept in the configuration and never consulted — Grok does
  not even compile it.

## Event names

Grok accepts several spellings of each event and normalizes them, so a hooks
file shared with Claude Code or Cursor loads unchanged. All of these are
accepted and none is a finding:

- The 15 names Grok documents: `SessionStart`, `SessionEnd`,
  `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`,
  `PermissionDenied`, `Stop`, `StopFailure`, `StopCancelled`,
  `Notification`, `SubagentStart`, `SubagentStop`, `PreCompact`,
  `PostCompact`.
- `SubagentEnd`, Grok's documented alias for `SubagentStop`.
- The `snake_case` spelling of each, the wire name the hook itself receives
  in `GROK_HOOK_EVENT`.
- The `camelCase` spelling of each, with one exception: `userPromptSubmit`
  is *not* accepted. Write `UserPromptSubmit`, `user_prompt_submit`, or
  Cursor's `beforeSubmitPrompt`.
- Cursor's per-operation names, which map to the generic tool events:
  `beforeShellExecution`, `beforeMCPExecution` and `beforeReadFile` become
  `PreToolUse`; `afterShellExecution`, `afterMCPExecution`, `afterFileEdit`,
  `afterAgentResponse` and `afterAgentThought` become `PostToolUse`.

## Examples

**Bad** — the string `timeout` costs every hook in the file, including the
`Stop` hook under another event:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          { "type": "command", "command": "./scripts/version.sh", "timeout": "10" }
        ]
      }
    ],
    "Stop": [
      { "hooks": [{ "type": "command", "command": "make lint" }] }
    ]
  }
}
```

**Good** — one matcher group per event, each handler carrying the field its
type needs:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|run_terminal_command",
        "hooks": [
          { "type": "command", "command": "./scripts/audit-command.sh", "timeout": 5 }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          { "type": "command", "command": "make lint", "timeout": 600 },
          { "type": "http", "url": "https://hooks.example.com/turn-ended", "timeout": 10 }
        ]
      }
    ]
  }
}
```

## How to fix

- Write `timeout` as a non-negative integer of seconds (`30`, not `30.0` or
  `"30"`), and give a `Stop` or `SubagentStop` gate enough of them for the
  command it runs.
- Give every handler a `type`, and the field that type needs: `command` for
  a `command` handler, `url` for an `http` one.
- Keep `env` values as strings, and set anything the runner already injects
  inside the script rather than in `env`.
- Match one of the event spellings above, and drop a `matcher` from `Stop`
  and `UserPromptSubmit` — put the condition in the script, which receives
  the event as JSON on stdin.
- Split a matcher into a group per pattern rather than reaching for a
  construct Rust's regex engine does not have.

Grok adds events faster than skillsaw releases. Rather than turning the rule
off, name the new one:

```yaml
rules:
  grok-hooks-valid:
    # An event name Grok dispatches that this release has not heard of.
    extra-events:
      - PreSomethingNew
```
