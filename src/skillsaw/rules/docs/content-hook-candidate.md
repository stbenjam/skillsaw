## Why

Prose instructions like "always run the formatter before committing"
depend on the model choosing to follow them every time. Hooks execute
deterministically on every matching event — they cannot be forgotten or
deprioritized. Converting automatable instructions to hooks makes the
behavior reliable instead of aspirational.

## Examples

**Bad:**

```markdown
Always run `prettier --write` after every change.
Run tests before every commit.
```

**Good (hooks.json):**

```json
{
  "hooks": {
    "PostToolUse": [
      {"hooks": [{"type": "command", "command": "prettier --write ."}]}
    ]
  }
}
```

## How to fix

Move the instruction into a hook configuration (`.claude/hooks.json` or
equivalent). Use the hook type suggested in the violation message
(e.g., `pre-commit`, `PostToolUse`, `Stop`). You can keep a brief note
in the instruction file referencing the hook for documentation purposes.
