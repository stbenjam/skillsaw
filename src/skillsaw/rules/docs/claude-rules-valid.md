## Why

Files in `.claude/rules/` are loaded as scoped instructions. They
must be markdown (`.md`) files and, if they contain frontmatter, the
optional `paths` field must be a valid list of globs. A non-markdown
file or invalid frontmatter will be silently ignored or cause a
parse error.

## Examples

**Bad:**

```
.claude/rules/testing.txt
```

**Bad (invalid frontmatter):**

```markdown
---
paths: "src/**"
---

Run tests before committing.
```

**Good:**

```markdown
---
paths:
  - "src/**"
  - "tests/**"
---

Run tests before committing.
```

## How to fix

Ensure rule files use the `.md` extension. If the file has
frontmatter, the `paths` field must be a YAML list of glob patterns
(not a bare string). Remove any unrecognized frontmatter keys.
