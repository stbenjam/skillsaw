## Why

Codex installs only what the catalog lists, and it skips catalog entries
it cannot resolve rather than reporting an error. Both halves of that
failure are silent: a plugin directory missing from
`.agents/plugins/marketplace.json` is never installable, and an entry
pointing at a directory that does not exist — or that has no
usable legacy `.codex-plugin/plugin.json` or supported portable root
`plugin.json` — quietly disappears from the marketplace.

## Examples

**Bad:**

```json
{
  "name": "example-codex-plugins",
  "plugins": [
    {"name": "note-taker", "source": {"source": "local", "path": "./plugins/gone"}}
  ]
}
```

with `plugins/note-taker/.codex-plugin/plugin.json` on disk and no
`plugins/gone` directory.

**Good:**

```json
{
  "name": "example-codex-plugins",
  "plugins": [
    {
      "name": "note-taker",
      "source": {"source": "local", "path": "./plugins/note-taker"},
      "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
      "category": "Productivity"
    }
  ]
}
```

## How to fix

Register the plugin, or repair the entry that does not resolve.

Plugins are registered across catalogs in `.agents/plugins/`. Local entries
register the directory their `path` resolves to, while remote entries register by `name`.
If a local plugin's directory is not reached by any entry path, update the `path` field in the catalog.


Entry names that disagree with the plugin manifest's `name` are reported as warnings.


`skillsaw fix --suggest` adds a complete entry — `name`, a `local`
source, `policy`, and `category` — for each unregistered plugin. It
declines whenever appending an entry cannot fix the problem:

- The catalog cannot be rewritten safely — unparseable JSON, a
  duplicate object key, a non-object root, or a non-list `plugins` key.
  `codex-marketplace-json-valid` reports those shapes; repair them by
  hand first.
- Some catalog entry already spells the plugin's name. Appending a
  duplicate would be a no-op that leaves the violation standing; the
  existing entry's `path` is what needs correcting.
- Two discovered directories declare the same name. Registering one
  would silence the other without making it installable.
- The manifest declares no valid `name` of its own. Legacy manifests use
  kebab case; portable manifests may use their schema-valid canonical
  identifier, including dots. A directory-name fallback is never published.
- The selected compatibility overlay is malformed. Repair it before
  registering the portable package; an object-valued inline OpenAI extension
  takes precedence over that compatibility file.
- The plugin lies outside the marketplace root, where a `local` source
  cannot reach it — `..` is not allowed in a source path.

Entries whose source is missing or lacks a manifest are likewise never
auto-fixed: only you know whether the path or the directory is the
mistake. Plugins matching an `exclude` pattern are not reported at all,
which also keeps the fixer from publishing an excluded plugin.

Plugins under `.codex/plugins/` are never reported. That is where Codex
installs plugins into a developer's checkout, so they are not the
repository's to publish — their skills and hooks are still linted, but
demanding the repository's catalog list them would fail the lint of
anyone who installed one.
