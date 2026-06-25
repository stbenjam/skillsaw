## Why

Instruction and configuration files share the model's context window.
When a single file exceeds its recommended token limit, it crowds out
other files and degrades the model's ability to follow instructions
from any of them. Limits vary by file type — a CLAUDE.md has a larger
budget than a skill description.

## Examples

**Bad:**

A 25,000-token CLAUDE.md that includes full API documentation inline.

**Good:**

A 4,000-token CLAUDE.md with key instructions, linking to external
docs via `@references/` or `@` imports for detail.

## How to fix

Split large files into smaller, focused files. Move reference material
into `@`-imported files or `.claude/rules/` scoped rule files that
only load when relevant. For skill and command descriptions, shorten
the frontmatter `description` to a concise trigger phrase.

## Tuning

Override per-category token limits:

```yaml
rules:
  context-budget:
    limits:
      claude-md:
        warn: 8000
        error: 16000
      skill:
        warn: 4000
        error: 8000
```
