## Why

`.agents/plugins/marketplace.json` is the Codex catalog used for local, repository,
and team plugin distribution. Each entry needs a resolvable source plus explicit
installation, authentication, and category metadata.

## Examples

**Bad:**

```json
{
  "name": "local-plugins",
  "plugins": [{"name": "helper", "source": "../helper"}]
}
```

**Good:**

```json
{
  "name": "local-plugins",
  "plugins": [
    {
      "name": "helper",
      "source": {"source": "local", "path": "./plugins/helper"},
      "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
      "category": "Productivity"
    }
  ]
}
```

## How to fix

Use a kebab-case marketplace name and a `plugins` array. Give every entry a name,
supported source, policy object with `installation` and `authentication`, and category.
Local paths must start with `./` and stay inside the marketplace root. Git and npm
sources must include the fields required by their source type.

