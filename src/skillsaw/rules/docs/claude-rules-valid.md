## Why

Files in `.claude/rules/` are loaded as scoped instructions. They
must be markdown (`.md`) files and, if they contain frontmatter, the
optional `paths` field must be a valid list of globs. A non-markdown
file or invalid frontmatter will be silently ignored or cause a
parse error.

Validation covers the root `.claude/rules/` directory and conventional Claude
rule outputs beside discovered Rulesync projects, including nested packages.
Exclusions and repository containment apply. Recognized generated copies keep
these structural checks; generation does not make invalid consumer metadata
valid.

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
