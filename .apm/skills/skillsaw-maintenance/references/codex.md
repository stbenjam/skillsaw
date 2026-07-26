# OpenAI Codex plugin formats

<!-- Repo-root-relative src/... and manifest paths below are intentionally kept as prose, not navigable links. -->
<!-- skillsaw-disable content-unlinked-internal-reference -->

OpenAI plugins are shared by ChatGPT and Codex. Their manifests and local marketplace
catalogs differ from the legacy-compatible Claude plugin format, so skillsaw maintains
separate Codex nodes and rules.

## Upstream sources

- Plugin packaging and manifests: https://developers.openai.com/plugins/build/plugins
- Plugin architecture: https://developers.openai.com/plugins/concepts/plugins
- Codex plugin usage: https://learn.chatgpt.com/docs/plugins

## What to check

- `.codex-plugin/plugin.json` required identity fields and supported component fields.
- Manifest path rules for skills, MCP servers, apps, hooks, and interface assets.
- `.agents/plugins/marketplace.json` location, header metadata, and entry requirements.
- Marketplace source types and their required fields: local paths, Git-backed sources,
  and npm packages.
- Installation and authentication policy values.
- Codex discovery locations and legacy marketplace compatibility.

## skillsaw rules that map

- Detection and lint-tree nodes: `src/skillsaw/context.py`, `src/skillsaw/lint_tree.py`,
  and `src/skillsaw/lint_target.py`.
- Codex rules: `src/skillsaw/rules/builtin/codex/`:
  `codex-plugin-json-required`, `codex-plugin-json-valid`,
  `codex-marketplace-json-valid`, and `codex-marketplace-registration`.
- Bundled skills, hooks, and MCP configuration also flow through the shared `skills/`,
  `hooks/`, and `mcp/` rules after Codex plugin discovery.

## Sync notes

- Keep Codex rules separate from Claude rules. The formats use different manifest
  directories, marketplace locations, fields, policies, and source objects.
- `marketplace_json_valid.py` hand-copies the documented installation values and source
  type requirements. Recheck them whenever the packaging page changes.
- Unknown marketplace source types produce a warning rather than an error so an upstream
  extension does not make existing catalogs unusable.
- Local source paths resolve from the marketplace root, not from `.agents/plugins/`.
