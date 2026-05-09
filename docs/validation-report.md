# Real-World Validation Report

Validation run: 2026-05-09

## Repos Tested

### 1. openshift-eng/ai-helpers

- **Type detected**: marketplace
- **Plugins**: 39, **Skills**: 98, **Rules run**: 70
- **Errors**: 0, **Warnings**: 2

| # | Finding | Rule | Verdict |
|---|---------|------|---------|
| 1 | `.cursor/rules/idiomatic-go.mdc`: Missing frontmatter | cursor-mdc-valid | TRUE POSITIVE — file has no frontmatter, so Cursor treats it as Manual activation |
| 2 | `.cursor/rules/idiomatic-go.mdc`: Manual activation | cursor-activation-type | TRUE POSITIVE — consequence of missing frontmatter |

**Assessment**: Clean results. Both warnings are legitimate and correctly scoped (only fire because `.cursor/` exists).

### 2. auth0/agent-skills

- **Type detected**: marketplace
- **Plugins**: 1, **Skills**: 17, **Rules run**: 50
- **Errors**: 0, **Warnings**: 0

**Assessment**: Clean pass. No issues found.

### 3. anthropics/claude-plugins-official

- **Type detected**: marketplace
- **Plugins**: 50, **Skills**: 28, **Rules run**: 50
- **Errors**: 3, **Warnings**: 45

#### Errors (all true positives)

| # | Finding | Rule | Verdict |
|---|---------|------|---------|
| 1 | `plugins/session-report`: Missing plugin.json | plugin-json-required | TRUE POSITIVE — plugin listed in marketplace but has no plugin.json |
| 2 | `example-plugin` not registered in marketplace.json | marketplace-registration | TRUE POSITIVE — directory exists but not listed |
| 3 | `hookify/skills/writing-rules/SKILL.md`: Name mismatch | agentskill-name | TRUE POSITIVE — frontmatter name doesn't match directory |

#### Warnings (all true positives)

- 30 missing `version` or `author` fields in plugin.json (recommended fields)
- 12 missing README.md files (recommended for plugins)
- 1 non-kebab-case command name (`clean_gone`)
- 1 evals directory without evals.json
- 1 command missing frontmatter `description`

## False Positives Found and Fixed

### 1. MCP `.mcp.json` flat format not recognized (FIXED)

**Rule**: `mcp-valid-json`
**Problem**: The rule required `.mcp.json` files to use the `{"mcpServers": {...}}` wrapper format. In practice, Claude Code plugins use a flat format where server names are top-level keys: `{"my-server": {"type": "http", "url": "..."}}`. This produced 12 false ERROR-level violations on claude-plugins-official.
**Fix**: Updated `_validate_mcp_file()` to accept both the wrapped (`mcpServers` key) and flat (server names as top-level keys) formats. Also updated `McpProhibitedRule` for consistency. Added tests for both formats.
**Impact**: Eliminated 12 false errors.

### 2. Command sections not part of official format (FIXED)

**Rule**: `command-sections`
**Problem**: The rule required `## Name`, `## Synopsis`, `## Description`, and `## Implementation` sections in command files. The official Claude Code plugin command format uses YAML frontmatter (`description`, `argument-hint`) with free-form prose body — no required sections. This produced 99 false warnings on claude-plugins-official.
**Fix**: Disabled `command-sections` and `command-name-format` rules by default. They enforce conventions not present in the spec and can be opted into by users who want stricter formatting.
**Impact**: Eliminated 99 false warnings.

## False Negatives

No obvious false negatives identified. The remaining findings are all legitimate issues in the tested repos.

## Summary

| Metric | Before Fix | After Fix |
|--------|-----------|-----------|
| ai-helpers errors | 0 | 0 |
| ai-helpers warnings | 2 | 2 |
| agent-skills errors | 0 | 0 |
| agent-skills warnings | 0 | 0 |
| claude-plugins-official errors | 15 | 3 |
| claude-plugins-official warnings | 144 | 45 |
| False positives eliminated | — | 111 |
| Test suite | 1109 pass | 1112 pass |
