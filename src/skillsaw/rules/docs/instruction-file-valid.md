## Why

An instruction file (AGENTS.md, CLAUDE.md, GEMINI.md) that is empty
or unreadable provides no value — the agent loads it, spends overhead
processing it, and gets nothing. This usually indicates a file that
was created as a placeholder but never filled in.

## Examples

**Bad:**

An empty `CLAUDE.md` file (0 bytes).

**Good:**

```markdown
# Project Rules

Run `make test` before committing.
Use Go 1.22+.
```

## How to fix

Add meaningful content to the file, or delete it if it is not needed.
An absent file is better than an empty one — it avoids wasted
processing overhead.
