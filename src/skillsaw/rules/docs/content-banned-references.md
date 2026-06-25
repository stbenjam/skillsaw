## Why

Deprecated model names, retired API endpoints, and other banned references
rot silently — the model will still try to use them, producing errors or
unexpected behavior. Keeping references current avoids wasted tokens on
instructions that cannot succeed.

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

## How to fix

Replace deprecated model names with their current equivalents and update
retired API endpoints. Custom banned patterns configured via the `banned`
list should be replaced per the message in the violation. `skillsaw fix
--llm` can update flagged references automatically.

## Tuning

Add project-specific bans or disable the built-in checks:

```yaml
rules:
  content-banned-references:
    banned:
      - pattern: "\\blegacy-api\\b"
        message: "Use v2-api instead"
    skip-builtins: false
```
