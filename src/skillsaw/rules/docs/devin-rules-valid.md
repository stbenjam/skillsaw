## Why

Devin chooses when to load a workspace rule from the rule's YAML
frontmatter. A malformed or unsupported `trigger` can leave an apparently
authoritative file inactive. The activation data also depends on the mode:
`glob` needs usable repository-relative patterns, while `model_decision`
needs a description that lets the model route work to the rule.

Devin CLI reads rules below `.devin/rules/` and the legacy
`.windsurf/rules/` spelling at the workspace root and in nested projects.
Devin Desktop limits a workspace rule to 12,000 characters. Unknown
frontmatter keys are accepted so a new upstream field does not make an
otherwise valid rule fail.

Devin's documented bare glob scalar, such as `globs: **/*.test.ts`, parses
even though strict YAML reserves a leading `*` for aliases. This exception
applies only to the top-level `globs` value; unrelated malformed YAML is
still reported. The scalar itself is an error: Devin Desktop may accept a
single string, but the Devin CLI fails to load the rule ("expected a
sequence"). A YAML list is the one form both hosts read.

## Severity

Malformed YAML, an unsupported trigger, invalid activation data, and a rule
over the configured character limit are errors because Devin may ignore the
rule or be unable to activate it as intended.

`trigger` is optional. Without it Devin infers the mode: `globs` makes the
rule glob-activated, a `description` makes it agent-decidable, and a rule
with neither is manual (`@rule`). A rule that never activates on its own is
reported at info level.

## Examples

**Bad** — the glob escapes the repository:

```markdown
---
trigger: glob
globs:
  - ../shared/**
---

Use the shared API conventions.
```

**Good** — a model-selected rule with routing context:

```markdown
---
trigger: model_decision
description: Apply when changing public API response shapes.
---

Preserve backward compatibility for existing response fields.
```

## How to fix

- Set `trigger` to `always_on`, `manual`, `model_decision`, `agent`, or
  `glob`, or omit it and let Devin infer the mode from `globs` or
  `description`.
- For `glob`, provide a non-empty string or list of repository-relative
  patterns. Remove absolute paths and `..` path segments.
- For `model_decision`, add a non-empty string `description` that explains
  when the rule applies.
- Split or shorten a rule that exceeds `max-characters` (12,000 by default),
  or configure that option when a different host limit applies.
