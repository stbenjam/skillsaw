## Why

Deprecated model names, retired API endpoints, and outdated references can
cause models to fail or use obsolete interfaces. Keeping references up to date
ensures instructions work smoothly and efficiently.

When a line maps a name from skillsaw's built-in deprecation list to a
replacement (such as in a migration table, arrow syntax, or key/value pair),
skillsaw recognizes that the older name is being retired rather than
recommended. The replacement itself is still checked to ensure it points to a
current, supported model. Patterns you configure under `banned` are always
reported: they express your own policy, not a deprecation.

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
