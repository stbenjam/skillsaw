## Why

ZCode loads a plugin from `.zcode-plugin/plugin.json`, falling back to
`.claude-plugin/plugin.json` and then `.codex-plugin/plugin.json`. Its loader
skips the whole plugin when the manifest is not a JSON object or its `name` is
invalid. It also ignores component paths that are absolute or leave the plugin
directory, and it drops manifest-declared commands it cannot write out. None
of this stops ZCode from starting, so a broken plugin just goes missing.

This rule checks `.zcode-plugin/plugin.json` only. A Claude or Codex manifest
that ZCode falls back to is linted by that ecosystem's rules.

## Severity

**Errors**: ZCode skips the plugin or one of its components.

- Invalid JSON, or a manifest that is not an object.
- A `name` that is not 1–128 characters of lowercase letters, digits, `.`,
  `_` or `-`, starting with a letter or digit.
- A `skills`, `commands`, `agents`, `hooks` or `mcpServers` path that is
  absolute or contains `..` past the plugin root.
- A `hooks` path that is not a file (a missing path, or a directory).
- An object-form `commands` entry with an invalid name, or one that does not
  set exactly one of `source` and `content`, or whose `source` file is missing.

**Warnings**: the plugin loads, but part of it does nothing.

- `channels`, `lspServers`, `outputStyles` or `settings`, which ZCode
  recognises but does not load.
- A `skills` path that does not exist.

## How to fix

Give the plugin a lowercase name and keep every component path relative to
the plugin directory:

```json
{
  "name": "release-notes",
  "version": "1.2.0",
  "description": "Drafts release notes from merged pull requests",
  "skills": "./skills",
  "commands": {
    "draft-notes": { "source": "./commands/draft-notes.md", "description": "Draft notes" }
  },
  "mcpServers": "./.mcp.json"
}
```

Remove components ZCode does not load, or keep them only if another host
reads the same manifest.
