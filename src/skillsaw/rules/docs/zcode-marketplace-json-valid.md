## Why

`zcode plugins marketplace add` reads a marketplace catalog from
`.claude-plugin/marketplace.json`, falling back to the root `marketplace.json`
that ZCode's own marketplace publishes. This rule checks that root file in a
repository that ships `.zcode-plugin` plugins and has no Claude catalog. A
Claude catalog is checked by `claude-marketplace-json-valid`.

ZCode rejects a catalog whose `name` is invalid, and drops entries that are
not objects or have no `name`. At install time it also refuses a local plugin
in three cases:

- its source directory is missing;
- it has no manifest and the entry does not set `"strict": false`;
- its manifest `name` differs from the entry's.

## Severity

All findings are errors: each one is a marketplace or plugin ZCode cannot add
or install.

- Invalid JSON, a catalog that is not an object, or an invalid `name`.
- `plugins` that is neither an array nor an object keyed by plugin name.
- An entry that is not an object or has no `name`.
- A `source` kind ZCode does not install (`npm`, `pip`, or an unknown kind),
  or a recognised kind missing its locator: `repo` for `github`, `url` for
  `git` and `url`, `path` and `url` for `git-subdir`, `path` for `directory`.
- A local `source` that leaves the marketplace directory or is not a
  directory. An entry with no `source` resolves to a directory named after
  the plugin.
- A listed plugin with no manifest and no `"strict": false`.
- A listed plugin whose manifest `name` differs from the entry's `name`.

Remote sources (`github`, `git`, `url`, `git-subdir`) and absolute
`directory` sources are not checked, because they do not resolve inside the
checkout.

## How to fix

```json
{
  "name": "acme-plugins",
  "description": "Acme's ZCode plugins",
  "plugins": [
    { "name": "release-notes", "source": "./plugins/release-notes" }
  ]
}
```

Make each entry's `name` match the plugin's `.zcode-plugin/plugin.json`, and
point `source` at a directory inside the repository.
