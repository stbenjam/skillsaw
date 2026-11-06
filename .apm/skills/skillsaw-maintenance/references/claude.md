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

## Conformance with the official validator
`claude plugin validate --json` decides whether a Claude plugin or
marketplace loads. Run `scripts/claude-conformance.py` with the Claude
Code version pinned in `tests/claude_conformance.json`; the
`claude-conformance` CI job does the same.

- When a new Claude Code release changes the validator, install it and run
  `scripts/claude-conformance.py --write`, which moves the pin; set the
  same version in `.github/claude-code/package.json` and refresh its
  lockfile with `npm install --package-lock-only`. Treat each
  changed fixture as a finding: fix the skillsaw rule or the fixture, or add
  a `note` saying why the two differ.
- Probe anything new with `claude plugin validate`, then confirm load
  behavior with `claude plugin install` under a throwaway
  `CLAUDE_CONFIG_DIR`. The validator also enforces submission policy (for
  example reserved names), which the installer accepts.
- Keep the overlap table in `docs/claude-validate.md` current.

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
- **A marketplace entry is the manifest when `plugin.json` is absent.** The
  [marketplace reference](https://code.claude.com/docs/en/plugins/marketplace-reference#how-an-entry-combines-with-plugin-json)
  says "**No `plugin.json`**: the entry is the manifest regardless of
  `strict`", and the [manifest reference](https://code.claude.com/docs/en/plugins-reference#manifest-file)
  says "The manifest is optional." Verified on 2026-11-06 with released
  Claude Code 2.1.319: entries with default and `strict: true` pointing at
  directories without `plugin.json` pass `claude plugin validate`, install,
  and are enabled. `claude-plugin-json-required` skips every directory a
  local Claude marketplace entry registers; do not restore the former
  `strict: false`-only exemption. It still reports a Claude plugin directory
  no entry registers: `claude plugin validate <dir>` fails there with
  "No manifest found in directory".
- **Marketplace and entry names follow the plugin-id grammar.** The
  [marketplace reference](https://code.claude.com/docs/en/plugins/marketplace-reference#top-level-fields)
  requires letters, digits, `.`, `_`, and `-`, starting with a letter or
  digit; only the marketplace `name` also forbids `..`. Verified on
  2026-11-06 with Claude Code 2.1.319: `claude plugin validate` fails
  `_p`, `-p`, `.p`, `a/b`, `ünï`, and names with spaces, fails a
  marketplace named `a..b`, and passes an entry named `a..b` and names like
  `my.market_1`. `claude-marketplace-json-valid` reports those as errors
  and keeps the kebab-case warning only for installable names.
- **Entry `hooks` must be an inline object.** Per
  [hooks in an entry](https://code.claude.com/docs/en/plugins/marketplace-reference#hooks-in-an-entry),
  `claude plugin validate` passes a path or array, but on 2.1.319 the
  installed plugin fails to load with `the file-path and array forms are
  not yet supported in a marketplace entry`. `claude-marketplace-json-valid`
  reports both forms; drop the check if a later release loads them.
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
  Project/APM agents still need names. Verified on 2026-11-06 with 2.1.319
  through session init: plugin agents and commands without frontmatter or a
  description load, so those findings are warnings; a project agent with no
  description is skipped and stays an error.
