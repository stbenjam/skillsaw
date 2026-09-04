## Why

Google Antigravity uses dedicated JSON configuration files under `.agents/` or `.agent/`
to register workspace components and customizations:
- `skills.json`: Registers skills and skill directories.
- `agents.json`: Registers custom subagents.
- `rules.json`: Registers workspace rules.

Syntax errors or non-object root structures prevent Antigravity from parsing
the registries and loading the declared workspace components.

## Examples

**Bad:**

```json
[
  "invalid-root-array"
]
```

**Good:**

```json
{
  "entries": [
    {
      "path": "skills/my-skill",
      "include_only": [
        "my-.*"
      ]
    }
  ],
  "inherits": [
    {
      "path": "shared.json"
    }
  ]
}
```

## How to fix

Ensure that:
- The configuration file (`skills.json`, `agents.json`, `rules.json`) is valid JSON.
- The root of the JSON file is a JSON object.
- Syntax errors, unterminated quotes, and non-finite numbers (NaN, Infinity) are resolved.
