# Claude Code formats

<!-- Repo-root-relative src/... and cross-reference paths below are intentionally kept as prose, not navigable links. -->
<!-- skillsaw-disable content-unlinked-internal-reference -->

Claude Code has several distinct formats. `.claude/` is NOT a plugin — it has its own
layout. Each format below maps to its own skillsaw rules.

## Upstream source(s)
- Plugins: https://docs.claude.com/en/docs/claude-code/plugins-reference
- Marketplaces: https://docs.claude.com/en/docs/claude-code/plugin-marketplaces
- `.claude/` directory: https://docs.claude.com/en/docs/claude-code/claude-directory
- Hooks: https://docs.claude.com/en/docs/claude-code/hooks
- MCP servers: https://docs.claude.com/en/docs/claude-code/mcp
- Skills / agents: https://docs.claude.com/en/docs/claude-code/skills

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
- Hooks — `src/skillsaw/rules/builtin/hooks/`: `hooks-json-valid`, `hooks-dangerous`,
  `hooks-prohibited`.
- MCP — `src/skillsaw/rules/builtin/mcp/`: `mcp-valid-json`, `mcp-prohibited`.
- Skills — `src/skillsaw/rules/builtin/skills/frontmatter.py`: `skill-frontmatter`.
- Agents — `src/skillsaw/rules/builtin/agents/frontmatter.py`: `claude-agent-frontmatter`.

## Sync notes
- `plugin_structure.py` and `command_format.py` are backward-compat import shims — the
  real rules live in the `plugins/` and `commands/` packages. Do not re-add rules to the
  shims.
- `.claude/` is detected in `discovery/detect.py`, not a rule package; format changes
  there affect which repo types `context.py` exposes.
