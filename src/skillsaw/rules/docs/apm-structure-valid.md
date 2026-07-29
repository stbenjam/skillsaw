## Why

APM repositories use a `.apm/` directory with a specific layout — one
or more recognized primitive subdirectories (`skills/`,
`instructions/`, `prompts/`, `agents/`, `context/`, `hooks/`,
`extensions/`), with each skill directory containing a `SKILL.md`.
Deviations from this structure mean the package manager cannot discover
or install the repository's contents.

This rule only inspects an `.apm/` directory that exists. A
consumer-only manifest — a root `apm.yml` that just declares
`dependencies:` and `targets:` to install, authoring no package content
— has no `.apm/` directory and is never flagged.

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
`instructions/`, `prompts/`, `agents/`, `context/`, `hooks/`, or
`extensions/`) and move your content into it. Each skill directory must
contain a `SKILL.md` file.
