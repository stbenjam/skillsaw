# skillsaw and `claude plugin validate`

Claude Code ships its own validator, `claude plugin validate <dir>`. It is
the reference for whether a Claude plugin or marketplace loads. skillsaw
checks the same files, plus content, security, and other hosts. This page
says where the two overlap and how skillsaw stays in agreement.

Run both if you can. The official validator knows the loader's exact
behavior for the Claude Code version you run. skillsaw adds checks the
validator does not make, runs without Claude Code installed, and covers
repositories that also target Codex, Cursor, Grok and other hosts.

## How the checks map

Measured against Claude Code 2.1.319.

| Official validator check | skillsaw rule | Status |
| --- | --- | --- |
| `plugin.json` is valid JSON with a string `name` and string `version` | [`claude-plugin-json-valid`](rules/claude-plugin-json-valid.md) | Overlap |
| Missing `description`, `author` or `version` (warning) | [`claude-plugin-json-valid`](rules/claude-plugin-json-valid.md) `recommended-fields` | Overlap |
| Plugin name not kebab-case (warning) | [`claude-plugin-naming`](rules/claude-plugin-naming.md) | Overlap |
| Component paths (`commands`, `agents`, `skills`, `hooks`, `mcpServers`, `outputStyles`, `lspServers`) missing or climbing out with `..` | [`claude-plugin-json-valid`](rules/claude-plugin-json-valid.md) | Overlap |
| `${user_config.KEY}` in MCP config without `userConfig.KEY` | [`claude-plugin-json-valid`](rules/claude-plugin-json-valid.md) | Overlap |
| `marketplace.json` schema: `name`, `owner.name`, `plugins`, string entry names | [`claude-marketplace-json-valid`](rules/claude-marketplace-json-valid.md) | Overlap |
| Entry `source` must start with `./`; a bare name needs `metadata.pluginRoot`; no `..` | [`claude-marketplace-json-valid`](rules/claude-marketplace-json-valid.md) | Overlap |
| Marketplace and entry names Claude Code cannot install | [`claude-marketplace-json-valid`](rules/claude-marketplace-json-valid.md) | Overlap |
| No `plugin.json` (note: the marketplace entry or directory name stands in) | [`claude-plugin-json-required`](rules/claude-plugin-json-required.md) skips marketplace-registered plugins | Overlap |
| `.mcp.json` syntax; server dropped for an empty or non-string `command` or non-array `args` | [`mcp-valid-json`](rules/mcp-valid-json.md) | Overlap |
| `hooks.json` syntax, unknown events and handler types, non-string `matcher`, `onFailure` values | [`claude-hooks-valid`](rules/claude-hooks-valid.md) | Overlap |
| Agent, command and skill frontmatter parses; missing `description` (warning) | [`claude-agent-frontmatter`](rules/claude-agent-frontmatter.md), [`claude-command-frontmatter`](rules/claude-command-frontmatter.md), [`agentskill-valid`](rules/agentskill-valid.md) | Overlap |
| `SKILL.md` `metadata` that is not a mapping | [`agentskill-valid`](rules/agentskill-valid.md) | Overlap |
| Plugin has a README (`--profile directory`) | [`claude-plugin-readme`](rules/claude-plugin-readme.md) | Overlap |
| Reserved plugin names (`claude-*`, `anthropic-*`, ...) | — | Official only: a submission policy; `claude plugin install` accepts them |
| `http://` MCP URL to a non-loopback host (warning) | — | Official only |
| Unquoted `${CLAUDE_PLUGIN_ROOT}` in a shell-form hook (warning) | — | Official only |
| `CLAUDE.md` at the plugin root is not loaded (warning) | — | Official only |
| Plugin directory submission checks: LICENSE, icon, privacy policy URL | — | Official only |
| Project agent in `.claude/agents` with no `name` or `description`, which Claude Code skips | [`claude-agent-frontmatter`](rules/claude-agent-frontmatter.md) | skillsaw only: the validator does not flag it |
| Entry `hooks` written as a path or array, which the validator accepts but the installed plugin fails to load | [`claude-marketplace-json-valid`](rules/claude-marketplace-json-valid.md) | skillsaw only: the validator does not flag it |
| Plugin directories the catalog does not list | [`claude-marketplace-registration`](rules/claude-marketplace-registration.md) | skillsaw only |
| Dangerous hooks, committed secrets, hidden instructions | [`hooks-dangerous`](rules/hooks-dangerous.md), [`content-embedded-secrets`](rules/content-embedded-secrets.md) and the security rules | skillsaw only |
| Content quality, context budget, cross-host checks | content, context-budget and per-host rules | skillsaw only |

For the Claude format rules, severity follows the loader. A plugin agent
or command with no frontmatter still loads under its filename, so skillsaw
reports it as a warning. A project agent with no `description` is
skipped, so skillsaw reports it as an error.

skillsaw keeps the overlapping checks for CI runs and editors without
Claude Code. It does not add checks that only repeat the validator's
advisory warnings.

## Conformance check

`tests/claude_conformance.json` records, for every fixture under
`tests/fixtures/` that holds a `.claude-plugin/` directory:

- `official`: what the validator says will not load (its errors, and the
  warnings that say an entry or server is ignored or dropped at load time);
- `skillsaw`: the rules skillsaw reports at error severity;
- `note`: why they differ, required when only one side reports an error.

The pytest suite checks the skillsaw half on every run. The validator half
runs in the `claude-conformance` CI job, which installs the Claude Code
version the manifest pins. Locally, with that version installed:

```bash
scripts/claude-conformance.py            # compare; exit 1 on drift
scripts/claude-conformance.py --write    # re-record after an intended change
```

When Claude Code releases a version that changes the validator, install it
and run `--write`, which also moves the pin to that version. Review the
diff, then fix any new disagreement in a skillsaw rule or fixture.
