## Why

`@path` import references in instruction files tell the agent to
include additional context at load time. An import that points to a
nonexistent file is silently skipped — the instructions it was
supposed to provide are missing, and no error is surfaced.

## Examples

**Bad:**

```markdown
@docs/old-guidelines.md

- Review @docs/deploy-checklist.md before release.
```

**Good:**

```markdown
@docs/guidelines.md

- Review @docs/release-checklist.md before release.
```

## How to fix

Update the import path to point to the correct file. If the file was
deleted or renamed, either update the reference or remove the import
line. Imports in loaded files are resolved relative to the file that
contains them, and recursively imported files are checked up to four
hops. Imports must not escape the repository root.
