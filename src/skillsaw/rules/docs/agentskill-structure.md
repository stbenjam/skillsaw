## Why

The agentskills.io specification defines a fixed set of recognized
subdirectories inside a skill directory (`evals/`, `references/`,
etc.). Unrecognized subdirectories may be silently ignored by skill
loaders or cause validation errors in stricter runtimes.

## Examples

**Bad:**

```
my-skill/
  SKILL.md
  helpers/       # not in spec
  test-data/     # not in spec
```

**Good:**

```
my-skill/
  SKILL.md
  evals/
  references/
```

## How to fix

Move files into recognized subdirectories or up to the skill root.
If the extra directory is intentional, consider whether its contents
belong in `references/` or should live outside the skill directory
entirely.
