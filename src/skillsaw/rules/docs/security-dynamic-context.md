## Why

Some agent clients support dynamic context injection in agent-facing content.
[Claude Code's documentation](https://code.claude.com/docs/en/skills#inject-dynamic-context)
describes the inline form, `` !`<command>` ``, and fenced blocks whose info
string is `!`. These forms execute shell commands before content is sent to
the model, and the command output is inserted into the prompt — turning
otherwise static content into a shell execution surface that can expose
repository data or run an unexpected command during context loading.

As defense in depth, this rule scans every content block that skillsaw
attaches to the lint tree rather than tying the check to one client or
format: prose files are routinely cross-loaded into surfaces that do expand
the syntax, and other clients can adopt the same mechanism.

This rule treats dynamic context as prohibited unless the exact command has
been reviewed and added to an explicit allowlist. It is enabled automatically
so every repository gets this supply-chain check, and reports at `warning`
severity by default so adopting a new skillsaw release does not fail
previously-clean CI runs; raise it to `error` for a hard gate.

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
    enabled: auto
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

Ordinary inline code is not dynamic context. The established inline form is
recognized only when `!` is at the start of a line or immediately follows
whitespace. An exclamation marker immediately after `KEY=` is left literal by
clients following the documented convention.

## How to fix

Remove the dynamic context command when the content does not need live shell
output. If it is intentional, review the command and add the exact inline
command or complete fenced command block to `allowlist`. Exact matching means
that adding arguments or changing whitespace in a command causes it to be
reported again.

For a centrally managed policy, Claude Code also supports disabling skill
shell execution with `disableSkillShellExecution`; that setting prevents
these commands from running even when content contains them. Other clients
may offer an equivalent setting.
