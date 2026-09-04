## Why

Google Antigravity uses dedicated JSON configuration files under `.agents/` or `.agent/`
to register workspace components and customizations:
- `skills.json`: Registers skills and skill directories.
- `agents.json`: Registers custom subagents.
- `rules.json`: Registers workspace rules.

This rule validates that Antigravity registry JSON files (`skills.json`, `agents.json`, `rules.json`)
under `.agents/` or `.agent/` are valid JSON objects. Syntax errors, non-object root structures,
or non-finite numbers prevent Antigravity from parsing the registries and loading the declared
workspace components.

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
  "skills": []
}
```

## How to fix

- Format the configuration file (`skills.json`, `agents.json`, `rules.json`) as valid JSON.
- Define a JSON object at the root of the file rather than an array or primitive value.
- Fix any syntax errors, unterminated strings, and non-finite numbers (`NaN`, `Infinity`).
