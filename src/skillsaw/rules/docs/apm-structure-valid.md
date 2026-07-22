## Why

APM repositories use a `.apm/` directory with a specific layout — one
or more recognized primitive subdirectories (`skills/`,
`instructions/`, `prompts/`, `agents/`, `context/`, `hooks/`), with
each skill directory containing a `SKILL.md`. Deviations from this
structure mean the package manager cannot discover or install the
repository's contents.

## Examples

**Bad:**

```
.apm/
  my-skill/
    README.md
```

**Good:**

```
.apm/
  skills/
    my-skill/
      SKILL.md
```

## How to fix

Create a recognized primitive subdirectory inside `.apm/` (`skills/`,
`instructions/`, `prompts/`, `agents/`, `context/`, or `hooks/`) and
move your content into it. Each skill directory must contain a
`SKILL.md` file.
