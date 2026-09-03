## Why

Plugin names appear in command identifiers (`plugin:command`) and
configuration files. A name that uses uppercase, underscores, or
spaces breaks conventions and may cause lookup failures in
case-sensitive systems.

## Examples

**Bad:**

```json
{"name": "My_Plugin"}
```

**Good:**

```json
{"name": "my-plugin"}
```

## How to fix

Rename the plugin to use kebab-case in `plugin.json` and rename the
plugin directory to match.

## Another ecosystem's plugins

This is a Claude-format convention. A directory claimed only by another
ecosystem — OpenAI Codex or Grok Build, through a
`.codex-plugin/plugin.json`, a `.grok-plugin/plugin.json`, or a
local-source listing in either's catalog, with no `.claude-plugin` marker
and no Claude marketplace listing — is exempt: `codex-plugin-json-valid` already checks the
manifest name for that ecosystem, and a second directory-name report
would double up. A dual-manifest
directory keeps this check, and the ecosystem-neutral content and
security rules read every plugin's files regardless of provenance.
