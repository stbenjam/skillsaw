# Claude Code formats

<!-- Repo-root-relative src/... and cross-reference paths below are intentionally kept as prose, not navigable links. -->
<!-- skillsaw-disable content-unlinked-internal-reference -->

Claude Code has several distinct formats. `.claude/` is NOT a plugin — it has its own
layout. Each format below maps to its own skillsaw rules.

## Upstream source(s)
- Plugins: https://code.claude.com/docs/en/plugins-reference
- Marketplaces: https://code.claude.com/docs/en/plugin-marketplaces
- `.claude/` directory: https://code.claude.com/docs/en/claude-directory
- Hooks: https://code.claude.com/docs/en/hooks
- MCP servers: https://code.claude.com/docs/en/mcp
- Skills / agents: https://code.claude.com/docs/en/skills

## What to check
- **Plugins**: new required fields in `plugin.json`; command format/frontmatter changes;
  structural changes to plugin layout.
- **Marketplace**: `marketplace.json` requirements; plugin registration/discovery changes.
- **.claude/**: supported files/subdirs, discovery conventions (commands, skills, hooks,
  agents, settings).
- **Hooks**: hook event names, config shape, dangerous/prohibited patterns.
- **MCP**: server config shape as embedded in Claude Code (`.mcp.json` / `mcpServers`);
  see also `references/mcp.md` for the protocol spec itself.
- **Skills/agents**: frontmatter fields for skills and agents.

## skillsaw rules that map
- Plugins — package `src/skillsaw/rules/builtin/plugins/`: `claude-plugin-json-required`,
  `claude-plugin-json-valid`, `claude-plugin-naming`, `claude-plugin-readme`. (Back-compat shim:
  `plugin_structure.py`.)
- Commands — package `src/skillsaw/rules/builtin/commands/`: `claude-command-frontmatter`,
  `claude-command-name-format`, `claude-command-naming`, `claude-command-sections`. (Back-compat shim:
  `command_format.py`.)
- Marketplace — `src/skillsaw/rules/builtin/marketplace/`: `claude-marketplace-json-valid`,
  `claude-marketplace-registration`.
- `.claude/` detection — `src/skillsaw/discovery/detect.py` (`is_dot_claude`,
  the `dot-claude` marker returned by `marker_types`); `src/skillsaw/context.py`
  maps that marker to `RepositoryType.DOT_CLAUDE`.
- Hooks — `src/skillsaw/rules/builtin/hooks/`: `claude-hooks-valid`, `hooks-dangerous`,
  `hooks-prohibited`.
- MCP — `src/skillsaw/rules/builtin/mcp/`: `mcp-valid-json`, `mcp-prohibited`.
- Skills — `src/skillsaw/rules/builtin/agentskills/valid.py`: `agentskill-valid`.
- Agents — `src/skillsaw/rules/builtin/agents/frontmatter.py`: `claude-agent-frontmatter`.

## Sync notes
- **Plugin versions are strings, not semver.** The current
  [manifest version reference](https://code.claude.com/docs/en/plugins-reference#version)
  explicitly permits version strings without a semantic-version constraint.
  Verified on 2026-10-01 with released Claude Code 2.1.286:
  `claude plugin validate` accepts `v1`, `release-candidate`, `2026.10`, and
  `1.0.0garbage`, while numeric and null values fail. Keep the string type
  check in `claude-plugin-json-valid`; do not restore the former semver regex.
- `plugin_structure.py` and `command_format.py` are backward-compat import shims — the
  real rules live in the `plugins/` and `commands/` packages. Do not re-add rules to the
  shims.
- `.claude/` is detected in `discovery/detect.py`, not a rule package; format changes
  there affect which repo types `context.py` exposes.
- **Plugin agent names fall back to the filename.** The
  [agent loading reference](https://code.claude.com/docs/en/sub-agents#subagent-files-claude-code-skips)
  distinguishes plugin agents from project, user, and managed agents.
  Verified on 2026-10-01 with released Claude Code 2.1.286 through SDK
  initialization without a model turn: omitted, null, and empty plugin names
  produce `plugin-name:filename` agents. A project agent with an explicit name
  appears, while one without a name is skipped. `claude-agent-frontmatter`
  reads the tree's recorded plugin owner and cached declaration evidence to
  distinguish a plugin checkout named `.claude` from a project directory.
  Project/APM agents still need names, and description and YAML checks remain
  in place.
