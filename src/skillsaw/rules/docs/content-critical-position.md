## Why

LLM attention is strongest at the beginning and end of context and
weakest in the middle (the "lost in the middle" effect, Liu et al. 2023).
An instruction marked CRITICAL, IMPORTANT, or MUST that sits in the
middle of a long file is the one most likely to be silently dropped —
the emphasis signals it matters, but its position works against it.

This rule only activates on files longer than `min-lines` lines (default
50); short files do not exhibit a meaningful middle.

## Examples

**Bad** (line 80 of a 160-line CLAUDE.md):

```markdown
**CRITICAL**: Never push directly to main.
```

**Good** (same instruction, first section of the file):

```markdown
# Project rules

**CRITICAL**: Never push directly to main.
```

## How to fix

Move emphasized instructions into the first or last 25% of the file —
typically a "Rules" or "Critical" section at the top. If everything is
marked critical, nothing is: demote emphasis on lines that are merely
informative.

## Tuning

Raise `min-lines` if you maintain long files deliberately and only want
the rule to fire on very large ones:

```yaml
rules:
  content-critical-position:
    min-lines: 100
```
