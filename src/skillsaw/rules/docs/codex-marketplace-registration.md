## Why

A local Codex plugin that is absent from `.agents/plugins/marketplace.json` cannot be
discovered or installed from that marketplace.

## Examples

**Bad:** `plugins/research-helper/.codex-plugin/plugin.json` exists, but the marketplace
has no `research-helper` entry.

**Good:**

```json
{
  "name": "research-helper",
  "source": {"source": "local", "path": "./plugins/research-helper"},
  "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
  "category": "Productivity"
}
```

## How to fix

Add one entry under `plugins` whose `name` matches the plugin manifest and whose local
source path points to the plugin directory. Include the required policy and category
metadata.

