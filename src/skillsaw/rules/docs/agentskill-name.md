## Why

Skill names are identifiers used in configuration, logging, and
invocation commands. A name that does not match the directory name or
uses non-kebab-case creates confusion — users and tools expect the
skill name and its directory to correspond.

## Examples

**Bad:**

```yaml
---
name: DeployStaging
---
```

**Good (in a directory named `deploy-staging/`):**

```yaml
---
name: deploy-staging
---
```

## How to fix

Rename the `name` field in SKILL.md frontmatter to match the skill's
directory name, using lowercase letters and hyphens. `skillsaw fix`
can correct the name automatically.
