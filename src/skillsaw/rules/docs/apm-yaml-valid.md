## Why

`apm.yml` is the manifest for an APM (Agent Package Manager)
repository. Missing or invalid YAML, or missing required fields
(`name`, `version`), means the package manager cannot identify or
version the repository. Per the APM manifest schema only `name` and
`version` are required; `description` is optional but must be a string
when present.

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
required fields: `name` and `version`. Fix any YAML syntax errors
reported in the violation message.
