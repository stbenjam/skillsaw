## Why

Hooks execute arbitrary shell commands with no human review on every
matching event. In high-security environments, any hook that was not
explicitly reviewed and allowlisted represents an uncontrolled
execution vector — even legitimate hooks should be inventoried. This
rule inventories hooks in plugin `hooks/hooks.json` (Claude and Codex,
including Codex's manifest-declared and inline hooks), APM's compiled
copy, `.claude/settings*.json`, **skill/agent frontmatter** (`hooks:` key),
`<repo>/.codex/hooks.json` and any package's `.codex/hooks.json`,
`.muse/hooks.json`, and Cursor's `.cursor/hooks.json`.

A Cursor `type: "prompt"` hook runs no command, so there is nothing for a
command allowlist to match — it is reported whenever the rule is on. It is
still a hook: it fires on the same lifecycle events, and what it injects is
text the model acts on.

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
`allowlist` in your skillsaw config. Entries match the command spelling
shown in the diagnostic. This rule is disabled by default — enable it for
supply-chain-sensitive repositories.

For an exec-form hook, the diagnostic spelling joins `command` and `args`
with spaces; it does not preserve argument boundaries. Allowlisting only the
executable does not permit arbitrary arguments passed to it.
