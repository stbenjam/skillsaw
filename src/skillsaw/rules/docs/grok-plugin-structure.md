## Why

In Grok Build, a plugin package can be installed with or without an explicit
`plugin.json` manifest. When installing without a manifest, Grok discovers
plugins based on the presence of recognized component directories or files:
`skills/`, `agents/`, `hooks/hooks.json`, or `.mcp.json`.

If a plugin directory has neither a manifest nor recognized components, Grok
Build cannot install it when users attempt `grok plugin install`.

Additionally, directories containing only `commands/` or `.lsp.json` require
either a manifest or an accompanying component (such as a skill or hook) to be
recognized as installable packages during installation.

This rule verifies that directories intended as Grok plugins include either
an installable component or a manifest so users can install them smoothly.

## Severity

**Warning** — the directory lacks recognized components or a manifest, so Grok
cannot install it.

**Info** — when a catalog references a local plugin directory that lacks a
manifest, Grok installs it under a generated name (like `<dir>-<hash>`). Adding a
manifest with an explicit `name` ensures clean, predictable naming.

## Examples

**Bad** — contains only `commands/` without a manifest, so the installer cannot
register it:

```text
plugins/berth-notes/
├── README.md
└── commands/
    └── handover.md
```

**Good** — includes a manifest and recognized components:

```text
plugins/berth-notes/
├── .grok-plugin/
│   └── plugin.json
├── README.md
├── commands/
│   └── handover.md
└── skills/
    └── handover-note/
        └── SKILL.md
```

## How to fix

- Add a `.grok-plugin/plugin.json` with a `name` field to establish the
  plugin's identity.
- Alternatively, include standard components such as `skills/`, `agents/`,
  `hooks/hooks.json`, or `.mcp.json`.

If your build pipeline generates plugin files or manifests during packaging:

```yaml
rules:
  grok-plugin-structure:
    check-installable: false
```
