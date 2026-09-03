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
least its `name` and `path`.

`skillsaw fix` can append the missing entry, except when the
violation is reported without the fixable marker because the file
cannot be rewritten safely: `marketplace.json` is not valid JSON, its
root is not an object, `plugins` is not an array, or the plugin lives
outside `metadata.pluginRoot` (no valid relative `source` exists —
move the plugin under the plugin root or adjust `pluginRoot`).

## Another ecosystem's plugins

This rule covers the Claude marketplace. A directory claimed only by another
ecosystem — OpenAI Codex or Grok Build, through a
`.codex-plugin/plugin.json`, a `.grok-plugin/plugin.json`, or a
local-source listing in either's catalog, with no `.claude-plugin` marker
and no Claude marketplace listing — is exempt here, but registration is still
required: `codex-marketplace-registration` checks the same obligation
against the Codex catalog (`.agents/plugins/marketplace.json`). A
dual-manifest directory keeps this check, and the ecosystem-neutral
content and security rules read every plugin's files regardless of
provenance.
