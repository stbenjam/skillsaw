## Why

Project agent `.md` files need YAML frontmatter with `name` and
`description` so Claude Code can discover and register them. Plugin agents
can omit `name`: Claude Code uses the filename stem under the plugin's
namespace. The same fallback applies to empty or null names.

Claude Code skips a project agent whose frontmatter does not parse or has
no `description`, so those findings are errors. It loads a plugin agent
under its filename even without frontmatter or a description. This rule
still reports those as warnings, because Claude has nothing to delegate on
without a description.
See [Claude's agent loading rules](https://code.claude.com/docs/en/sub-agents#subagent-files-claude-code-skips)
for the distinction between project and plugin agents.

## Examples

**Bad:**

```markdown
# Code reviewer

Review pull requests for correctness and style...
```

**Good:**

```markdown
---
name: code-reviewer
description: Review pull requests for correctness and style issues.
  Use when the user asks to review a PR or diff.
---

# Code reviewer

Review pull requests for correctness and style...
```

## How to fix

Add a YAML frontmatter block with `description`, stating what the agent
does and when to invoke it. Project and APM agent files also require
`name`; plugin agents may use the filename instead. `skillsaw fix` can
add missing fields. When frontmatter already exists, the fix preserves
a plugin agent's filename fallback.
