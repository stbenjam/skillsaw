## Why

`marketplace.json` is the registry index for a plugin marketplace. If
it contains invalid JSON or is missing required fields, tools that
consume the marketplace cannot list or install plugins.

## Examples

**Bad:**

```json
{"plugins": []}
```

**Good:**

```json
{
  "name": "my-marketplace",
  "description": "Internal plugin marketplace",
  "plugins": []
}
```

## How to fix

Fix the JSON syntax error or add the missing required fields reported
in the violation message.
