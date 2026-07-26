## Why

`.codex-plugin/plugin.json` is the required entry point for an OpenAI plugin. Without
it, ChatGPT and Codex cannot identify or install the package.

## Examples

**Bad:** a plugin directory contains `skills/` but no manifest.

**Good:**

```json
{
  "name": "research-helper",
  "version": "1.0.0",
  "description": "Turn research notes into decisions",
  "skills": "./skills/"
}
```

## How to fix

Create `.codex-plugin/plugin.json` at the plugin root. Include a stable kebab-case
name, semantic version, description, and paths to the components the plugin bundles.

