## Why

Hooks execute arbitrary shell commands with no human review on every
matching event. In high-security environments, any hook that was not
explicitly reviewed and allowlisted represents an uncontrolled
execution vector — even legitimate hooks should be inventoried.

## Examples

**Bad (no allowlist configured):**

```json
{
  "hooks": {
    "PostToolUse": [
      {"hooks": [{"type": "command", "command": "scripts/format.sh"}]}
    ]
  }
}
```

**Good (with allowlist):**

```yaml
# .skillsaw.yml
rules:
  hooks-prohibited:
    allowlist:
      - "scripts/format.sh"
```

## How to fix

Review the flagged hook command and, if it is safe, add it to the
`allowlist` in your skillsaw config. Allowlist entries are exact-match,
so a modified version of the command will still be flagged. This rule
is disabled by default — enable it for supply-chain-sensitive
repositories.
