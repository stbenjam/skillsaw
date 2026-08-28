## Why

The Codex specification reserves `.codex-plugin/` for the manifest alone:
"Only `plugin.json` belongs in `.codex-plugin/`. Keep `skills/`,
`hooks/`, `assets/`, `.mcp.json`, and `.app.json` at the plugin root."
Files parked in the manifest directory are not discovered where Codex
looks for them, so hooks and assets stored there never load.

The exception is a path the manifest points at explicitly. Four plugins
in the official catalog (openai/plugins) keep their `interface` assets in
`.codex-plugin/assets/` and reference them as
`"./.codex-plugin/assets/logo.png"`, so Codex loads them from there. An
entry the manifest names is placed unconventionally, not stray, and this
rule stays quiet about it.

## Examples

**Bad:**

```text
my-plugin/
├── .codex-plugin/
│   ├── plugin.json
│   └── hooks.json      # never discovered
└── README.md
```

**Good:**

```text
my-plugin/
├── .codex-plugin/
│   └── plugin.json
├── hooks/
│   └── hooks.json
└── README.md
```

## How to fix

Move the reported file to the plugin root — `hooks/hooks.json` for
lifecycle hooks, `.mcp.json` for bundled MCP servers, `.app.json` for
registered MCP mappings, and `assets/` for icons and screenshots — then
point the matching `plugin.json` field at its new location.

If the file is deliberately shipped inside `.codex-plugin/`, referencing
it from `plugin.json` (as the official catalog does for `interface`
assets) is enough to satisfy this rule.
