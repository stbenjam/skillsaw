## Why

Agent Plugins v1 is the vendor-neutral plugin format: a root
`plugin.json`, skills at `skills/*/SKILL.md`, and an optional portable
`mcp.json`. It coexists with Claude Code and Codex formats in the same
directory, so publishing it costs two generated files per plugin — and
buys installation by any conforming client.

Agent Plugins coexists with Claude Code and Codex formats in the same
directory, so publishing it costs at most two generated files per
plugin (`mcp.json` only when the plugin has MCP configuration) — and
buys installation by any conforming client.

This opt-in rule turns that from a one-time conversion into a standing
guarantee: every plugin in the repository must carry the portable
manifest, shared metadata must not drift between the manifests, and a
Claude MCP configuration must have its portable counterpart. Enable it
in a marketplace's CI and new plugins cannot merge without the
vendor-neutral format.

## Bad

A marketplace plugin with only the Claude manifest:

```text
plugins/release-notes/
├── .claude-plugin/plugin.json
└── skills/draft-notes/SKILL.md
```

## Good

The same plugin with the portable manifest alongside:

```text
plugins/release-notes/
├── .claude-plugin/plugin.json
├── plugin.json                 # Agent Plugins v1
└── skills/draft-notes/SKILL.md
```

```json
{
  "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
  "name": "release-notes",
  "version": "1.4.0",
  "description": "Draft release notes from merged pull requests"
}
```

## How to fix

`skillsaw port --to agent-plugin .` converts every plugin in the
repository in one pass, or `skillsaw fix` applies the same
conversion through this rule's autofix. Both translate the manifest
metadata, convert a Claude `.mcp.json` to the portable transport names
and `${PLUGIN_ROOT}` placeholders, and skip anything the portable
format does not define (reporting what was skipped). Metadata drift
between the manifests is reported but never auto-edited.
