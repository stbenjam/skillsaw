## Why

Codex installs only what the catalog lists, and it skips catalog entries
it cannot resolve rather than reporting an error. Both halves of that
failure are silent: a plugin directory missing from
`.agents/plugins/marketplace.json` is never installable, and an entry
pointing at a directory that does not exist — or that has no
`.codex-plugin/plugin.json` — quietly disappears from the marketplace.

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

`skillsaw fix --suggest` adds a complete entry — `name`, a `local`
source, `policy`, and `category` — for each unregistered plugin. Entries
whose source is missing or lacks a manifest are not auto-fixed: only you
know whether the path or the directory is the mistake.

A plugin counts as registered when any catalog in `.agents/plugins/`
lists it, which is how a repository can split its plugins across
`marketplace.json` and a second catalog. Entry names that disagree with
the plugin manifest's own `name` are reported as warnings — Codex keys
installs off the catalog name, so the mismatch is confusing rather than
fatal. Remote sources (`url`, `git-subdir`, `npm`) are not resolved
locally and are never reported here.
