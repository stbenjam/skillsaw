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

`skillsaw fix` can append the missing entry, except when the
violation is reported without the fixable marker because the file
cannot be rewritten safely: `marketplace.json` is not valid JSON, its
root is not an object, `plugins` is not an array, or the plugin lives
outside `metadata.pluginRoot` (no valid relative `source` exists —
move the plugin under the plugin root or adjust `pluginRoot`).
