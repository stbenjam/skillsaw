## Why

The Codex plugin manifest defines package identity, bundled components, and install
surface metadata. Invalid JSON, malformed identity fields, unsafe paths, or references
to missing files make the package incomplete or unloadable.

## Examples

**Bad:**

```json
{
  "name": "Research Helper",
  "version": "latest",
  "skills": "../shared-skills"
}
```

**Good:**

```json
{
  "name": "research-helper",
  "version": "1.0.0",
  "description": "Turn research notes into decisions",
  "skills": "./skills/"
}
```

## How to fix

Use valid JSON and provide non-empty `name`, `version`, and `description` strings. Use
kebab-case for the name and semantic versioning for the version. Component and asset
paths must start with `./`, stay inside the plugin root, and point to existing files or
directories.

