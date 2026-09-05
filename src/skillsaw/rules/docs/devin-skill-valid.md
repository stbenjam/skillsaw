## Why

Skills in `.devin/skills/` use Devin's native dialect. Unlike portable Agent
Skills under `.agents/skills/` and `.windsurf/skills/`, their frontmatter is
optional and the directory name supplies the default name.
When frontmatter is present, however, values with the wrong shape can keep
tools, permissions, activation, or delegation settings from taking effect.

This rule validates Devin's documented fields while tolerating unknown keys
for forward compatibility. The skill body still receives skillsaw's shared
content-quality and security checks.

## Severity

Malformed YAML and invalid field types are errors. Setting both a named
`agent` and `subagent: true` is informational: Devin uses the named agent, so
the finding explains the precedence without treating a documented
combination as invalid.

## Examples

**Bad** — tool permissions and triggers have the wrong shapes:

```markdown
---
allowed-tools: 4
permissions:
  allow: Read(src/**)
triggers:
  - autonomous
---
```

**Good** — a configured native skill:

```markdown
---
argument-hint: "[path]"
model: sonnet
allowed-tools: Bash(openspec:*)
permissions:
  allow:
    - Read(src/**)
triggers:
  - user
  - model
---

Review the selected path and report actionable findings.
```

A native skill with no frontmatter, an empty header, or a comment-only
header is also valid. An explicit `null` document between the delimiters
is invalid. Optional string fields,
`allowed-tools`, `permissions`, and `triggers` may be omitted or null to use
Devin's defaults. The nested `permissions.allow`, `permissions.deny`, and
`permissions.ask` lists may also be null. `subagent` still requires a boolean
when present; `subagent: null` prevents the skill from loading.

## How to fix

- Use strings for `name`, `description`, `argument-hint`, `model`, and
  `agent`, and a boolean for `subagent`.
- Make `allowed-tools` a string or a list of strings.
- Make `permissions` an object; its `allow`, `deny`, and `ask` values must be
  lists of strings.
- Make `triggers` a non-empty list containing only `user` and/or `model`.
- When both delegation fields are present, remove `subagent: true` if the
  named `agent` already expresses the intended behavior.
