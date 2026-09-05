## Activation

This rule is opt-in while Muse loader compatibility and public repository
coverage are still limited. Enable it with `--rule muse-hooks-valid` or:

```yaml
rules:
  muse-hooks-valid:
    enabled: true
```

Hook discovery and the shared `hooks-dangerous` and `hooks-prohibited` rules
keep their existing activation settings independently of this shape rule.

## Why

`.muse/hooks.json` lets you automate shell commands during Muse Code agent
lifecycle events — such as right before a tool runs, when a session starts,
or when the agent finishes its work. Because hooks are committed to the
repository, they provide a reliable, shared way to automate setup and
checks for everyone on the team.

During headless runs, Muse Code executes hooks quietly without printing
console warnings if a configuration option is unsupported. When a hook
doesn't trigger, it can be hard to tell whether the event simply hasn't fired
yet or was skipped due to an unrecognized field. This rule inspects
`.muse/hooks.json` against Muse's supported events, matcher groups, and handler
options so that your automations run smoothly and reliably.

The commands themselves are also scanned for risky patterns by
[`hooks-dangerous`](hooks-dangerous.md) and can be inventoried against an
explicit allowlist with [`hooks-prohibited`](hooks-prohibited.md).

## Severity

Severity reflects the impact on your hook configuration:

**Errors** — prevent the entire file, a matcher group, or a specific handler
from running:

- *The whole file is skipped*: invalid JSON, non-finite numbers (`NaN`,
  `Infinity`, `-Infinity`), an event value that is not an array, a matcher
  group that is not an object, a non-string `matcher`, a group missing its
  `hooks` array, a handler that is not an object, or a known handler field
  of the wrong type (such as `timeout: "10"` or `async: 1`).
- *A matcher group is skipped*: keys other than `matcher` and `hooks` (such
  as a leftover `description` from a Claude Code hooks file). Sibling groups
  and other events continue to load.
- *A handler is skipped*: a missing `type`, a type other than `command`, an
  empty `command`, an unrecognized handler key, or options unsupported by
  Muse (`if`, `once: true`, `asyncRewake: true`). Other handlers in the
  same group continue to run.

**Warnings** — the file loads, but specific hooks or matchers may not run as
intended:

- Unrecognized event names. Event names are case-sensitive (e.g.
  `SessionStart` vs `sessionStart`).
- The `Setup` event, which Muse parses from Claude Code configurations but
  does not execute.
- An empty `hooks` object, event array, or matcher-group `hooks` array
  (valid JSON, but configures no actions).
- A regex `matcher` that does not compile under Rust's regex engine. Muse
  uses Rust's regex syntax, which supports Unicode property classes
  (`\p{...}`), character-class set operations (`&&`, `--`, `~~`), named
  capture groups (`(?<name>...)`), and `\z`, but does not support lookarounds,
  backreferences, or conditional/atomic groups. Matchers longer than 1,000
  characters are skipped to keep checks fast.
- A handler defining `commandWindows` without a fallback `command` for Linux
  or macOS environments.

**Info** — advisory notices:

- Events present in Muse's binary but omitted from official documentation
  (`Notification`, `PostToolUseFailure`, `StopFailure`, `PostToolBatch`).
  Be sure to test these in your environment before relying on them.

When an unknown key appears across multiple groups or handlers — common
when migrating a file from another tool — skillsaw groups them into a
single concise finding.

## Examples

**Bad** — an unexpected key prevents the first matcher group from running,
and an unsupported handler option is dropped:

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

**Good** — matcher groups using Muse's supported fields and PascalCase event names:

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

- Give each matcher group only `hooks` and, optionally, `matcher`. Notes or
  descriptions can be kept in companion documentation or inside invoked hook scripts.
- Give every handler `"type": "command"` and a non-empty `command` string.
  Include a POSIX `command` alongside any `commandWindows` so your hooks work
  across all platforms.
- When migrating from Claude Code: combine `args` into the `command` string,
  set environment variables within the script, and handle conditional logic
  directly in the command script.
- Specify `timeout` as a non-negative integer representing seconds (`30`,
  rather than `30.0` or `"30"`).
- Use Muse's standard PascalCase event names (e.g., `SessionStart`, `PreToolUse`).

If Muse introduces newer events, fields, or group keys, you can allow them
directly in your `.skillsaw.yaml` configuration without disabling the rule:

```yaml
rules:
  muse-hooks-valid:
    enabled: true
    # Additional event names dispatched by newer Muse releases:
    extra-events:
      - PreSomethingNew
    # Additional handler fields supported by newer Muse releases:
    extra-handler-fields:
      - retries
    # Additional matcher-group keys:
    extra-group-keys:
      - priority
```

## Matcher check limits

Matcher validation is conservative: it translates Rust inline flags and
braced hexadecimal escapes only for syntax checking. For example,
`Bash|(?i)Write`, `(?-u:\w+)`, `(?U).*`, `\x{42}ash`, `\u{42}ash` and
`\U{42}ash` are accepted.
Unclosed groups/classes and unsupported look-around/backreferences are still
reported in the checked subset. Extended-mode (`x`) patterns are left
unresolved because comments change tokenization. No finding is a complete
Rust regex validation guarantee.
