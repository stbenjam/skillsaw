## Why

`plugin.json` is the manifest declaring a Google Antigravity plugin package.
Antigravity reads plugin metadata (such as name, description, version, and author)
from this file. If the manifest contains invalid JSON, unexpected types, or
unrecognized fields, the plugin may fail to load or behave unpredictably.

## Examples

**Bad:**

```json
{
  "name": "Invalid Plugin Name!",
  "disabled": "yes",
  "extra_unknown": 123
}
```

**Good:**

```json
{
  "$schema": "https://antigravity.google/schemas/v1/plugin.json",
  "name": "my-plugin",
  "version": "1.0.0",
  "description": "Provides team utilities and workflows.",
  "author": {
    "name": "Team Dev"
  },
  "disabled": false
}
```

## How to fix

Ensure `plugin.json` is valid JSON and its root element is a JSON object.

Allowed fields in an Antigravity plugin manifest include:
- `name` (string, required): The name of the plugin, matching `^[a-zA-Z0-9-_]+$`.
- `$schema` (string, recommended): Schema URL (e.g., `"https://antigravity.google/schemas/v1/plugin.json"`).
- `description` (string, optional): A short summary of the plugin's purpose.
- `version` (string, optional): Plugin version string.
- `author` (string or object, optional): Author attribution (either a string or an object with `name`).
- `disabled` (boolean, optional): Whether the plugin is disabled.

Remove any unrecognized keys or fix type mismatches.
