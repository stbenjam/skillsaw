## Why

`apm.yml` is the manifest for an APM (Agent Package Manager)
repository. Missing or invalid YAML, or missing required fields
(`name`, `version`, `description`), means the package manager cannot
identify or version the repository.

## Examples

**Bad:**

```yaml
name: my-package
```

**Good:**

```yaml
name: my-package
version: "1.0.0"
description: Shared coding assistant skills for the frontend team
```

## How to fix

Create `apm.yml` at the repository root (if missing) and add the
required fields: `name`, `version`, and `description`. Fix any YAML
syntax errors reported in the violation message.
