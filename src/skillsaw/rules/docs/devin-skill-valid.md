## Why

Skills in `.devin/skills/` use Devin's native dialect. Unlike portable Agent
Skills under `.agents/skills/` and `.windsurf/skills/`, their frontmatter is
optional and the directory name supplies the default name.
When frontmatter is present, however, values with the wrong shape can keep
tools, permissions, activation, or delegation settings from taking effect.

This rule validates Devin's documented fields while tolerating unknown keys
for forward compatibility. The skill body still receives skillsaw's shared
content-quality and security checks.

A known field may appear only once, even when its value is null. This also
applies to `permissions.allow`, `permissions.deny`, and `permissions.ask`.
Duplicate unknown extension keys remain accepted. The finding points to the
repeated key; remove the duplicate and keep the intended value.

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

Native string fields retain scalar text such as `yes`, dates, and numbers.
String lists also accept scalar items, including `null` as the literal pattern
`null`. A scalar `allowed-tools` value still must be a string: numbers and
booleans only work as list items. Use `true` or `false` for `subagent`; YAML 1.1
spellings such as `yes`, `no`, `on`, and `off` do not load, nor does a quoted
`"true"`. These decoding rules apply only to Devin-native frontmatter. Devin ignores
YAML merge keys (`<<`); declare native fields explicitly instead.

## How to fix

- Use strings for `name`, `description`, `argument-hint`, `model`, and
  `agent`, and a boolean for `subagent`.
- Make `allowed-tools` a string or a list of strings.
- Make `permissions` an object; its `allow`, `deny`, and `ask` values must be
  lists of strings.
- Make `triggers` a non-empty list containing only `user` and/or `model`.
- When both delegation fields are present, remove `subagent: true` if the
  named `agent` already expresses the intended behavior.
