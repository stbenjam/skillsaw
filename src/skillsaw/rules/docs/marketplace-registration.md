## Why

A plugin that exists in the repository but is not registered in
`marketplace.json` is invisible to marketplace tooling — users
cannot discover or install it through the standard workflow.

## Examples

**Bad:**

A `deploy-plugin/` directory exists but `marketplace.json` has no
entry for it.

**Good:**

```json
{
  "plugins": [
    {
      "name": "deploy-plugin",
      "path": "deploy-plugin/"
    }
  ]
}
```

## How to fix

Add the plugin to the `plugins` array in `marketplace.json` with at
least its `name` and `path`. Use `skillsaw add plugin` to register
new plugins automatically.
