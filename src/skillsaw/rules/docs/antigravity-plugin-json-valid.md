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
  "name": "my-plugin",
  "version": "1.0.0",
  "description": "Provides team utilities and workflows.",
  "disabled": true
}
```

## How to fix

Ensure `plugin.json` is valid JSON and its root element is a JSON object.

Allowed fields in an Antigravity plugin manifest include:
- `name` (string, optional): The name of the plugin (kebab-case identifier).
- `version` (string, optional): Plugin version string.
- `description` (string, optional): A short summary of the plugin's purpose.
- `author` (string or object, optional): Author attribution.
- `disabled` (boolean, optional): Whether the plugin is disabled by default.

Remove any unrecognized keys or fix type mismatches.
