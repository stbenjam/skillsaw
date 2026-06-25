## Why

APM repositories use a `.apm/` directory with a specific layout —
`skills/` and/or `instructions/` subdirectories, each skill directory
containing a `SKILL.md`. Deviations from this structure mean the
package manager cannot discover or install the repository's contents.

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

Create a `skills/` or `instructions/` subdirectory inside `.apm/` and
move skill directories into it. Each skill directory must contain a
`SKILL.md` file.
