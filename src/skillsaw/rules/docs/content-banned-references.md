## Why

Deprecated model names, retired API endpoints, and other banned references
rot silently — the model will still try to use them, producing errors or
unexpected behavior. Keeping references current avoids wasted tokens on
instructions that cannot succeed.

A line that maps a banned name to a current replacement — a table row, an
arrow, or a key/value entry, in prose or inside a fence — is retiring the
name rather than recommending it, so the retired side is not reported. The
replacement side still is: a guide that migrates onto a deprecated model has
the same problem as one that never migrated.

## Examples

**Bad:**

```markdown
Use the `text-davinci-003` model for completions.
Call the `/v1/complete` endpoint.
```

**Good:**

```markdown
Use `claude-sonnet-4-6` for completions.
Call the `/v1/messages` endpoint.
```

**Also good — a migration guide naming what it retires:**

```markdown
| Retired id | Replacement |
| --- | --- |
| `claude-2.1` | `claude-sonnet-4-6` |
```

## How to fix

Replace deprecated model names with their current equivalents and update
retired API endpoints. Custom banned patterns configured via the `banned`
list should be replaced per the message in the violation. A coding agent can update flagged references automatically.

## Tuning

Add project-specific bans or disable the built-in checks:

```yaml
rules:
  content-banned-references:
    banned:
      - pattern: "\\blegacy-api\\b"
        message: "Use v2-api instead"
    skip-builtins: false
    report-migrations: false   # true also reports the retired side of a mapping
```
