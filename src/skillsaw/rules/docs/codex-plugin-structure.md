## Why

The Codex specification reserves `.codex-plugin/` for the manifest alone:
"Only `plugin.json` belongs in `.codex-plugin/`. Keep `skills/`,
`hooks/`, `assets/`, `.mcp.json`, and `.app.json` at the plugin root."
Files parked in the manifest directory are not conventionally discovered where
Codex looks for them. Explicitly referenced interface assets are an exception:
the official OpenAI catalog uses `.codex-plugin/assets/` for some icons and
logos. The rule accepts an entry containing an existing, contained file named by
`interface.composerIcon`, `logo`, `logoDark`, or `screenshots`. Missing, escaping,
and unreferenced assets do not receive this exception; manifest path validation
continues to check the references themselves.

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
