## Why

ZCode loads project subagents from the Markdown files directly inside
`.zcode/agents/`, and plugin subagents from a ZCode plugin's `agents/`
directory. It lists each subagent to the model as `name: description` and
uses that line to decide when to delegate. A file with no frontmatter, or no
non-empty `name` and `description`, is skipped. Plugin agents get no
filename fallback for `name`, unlike Claude Code's, so a plugin that ships
both a ZCode and a Claude manifest needs `name` for ZCode to load it.

## Severity

**Errors**: ZCode skips the agent.

- Missing frontmatter, or frontmatter that is neither valid YAML nor has
  `name:` and `description:` lines. ZCode reads frontmatter one `key: value`
  line at a time, so a value YAML rejects, such as an unquoted colon in
  `description: Use when: reviewing a PR`, still loads.
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
