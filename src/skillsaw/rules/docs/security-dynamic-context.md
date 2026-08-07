## Why

Claude Code supports [dynamic context injection](https://code.claude.com/docs/en/slash-commands#inject-dynamic-context) in skills and custom commands.
The inline form, `!`<command>``, and the fenced form, ` ```! `, execute shell
commands before the skill content is sent to Claude. The command output is
then inserted into the prompt, so this feature turns prompt content into a
shell execution surface and can expose repository data or run an unexpected
command during skill loading.

This rule treats dynamic context as prohibited unless the exact command has
been reviewed and added to an explicit allowlist. It is enabled automatically
so every repository gets this supply-chain check; repositories that do use
dynamic context must review and allowlist each command.

## Examples

**Bad:**

```markdown
## Pull request context

- Diff: !`gh pr diff`
```

**Good (with an explicit allowlist):**

```yaml
rules:
  security-dynamic-context:
    enabled: true
    allowlist:
      - "gh pr diff"
```

Multi-line dynamic context uses a fenced block and is matched as one command
including its line breaks:

```yaml
rules:
  security-dynamic-context:
    allowlist:
      - |-
        node --version
        git status --short
```

Ordinary inline code is not dynamic context. The inline form is recognized
only when `!` is at the start of a line or immediately follows whitespace;
for example, `KEY=!`cmd`` is left literal by Claude Code.

## How to fix

Remove the dynamic context command when the skill does not need live shell
output. If it is intentional, review the command and add the exact inline
command or complete fenced command block to `allowlist`. Exact matching means
that adding arguments or changing whitespace in a command causes it to be
reported again.

For a centrally managed policy, Claude Code also supports disabling skill
shell execution with `disableSkillShellExecution`; that setting prevents
these commands from running even when a skill contains them.
