## Why

ZCode loads project subagents from the Markdown files directly inside
`.zcode/agents/`. It lists each subagent to the model as `name: description`
and uses that line to decide when to delegate. A file with no frontmatter,
or no non-empty `name` and `description`, is skipped.

## Severity

**Errors**: ZCode skips the agent.

- Missing or malformed frontmatter.
- A missing or empty `name` or `description`, or one that is a list or a
  mapping.

**Warnings**: a `memory` value other than `user`, `project` or `local`. ZCode
ignores the value and loads the agent without memory.

## How to fix

```markdown
---
name: migration-reviewer
description: Reviews database migrations for locking and rollback safety.
memory: project
---

Review the migration in the current diff...
```
