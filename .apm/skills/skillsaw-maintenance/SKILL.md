---
name: skillsaw-maintenance
description: Analyze upstream specs (agentskills.io, Claude Code plugin/marketplace format) for changes, identify gaps in skillsaw's rule coverage, and create or update PRs to close those gaps. Use when performing periodic maintenance on the skillsaw linter.
compatibility: Requires git, gh CLI, and internet access
metadata:
  author: stbenjam
  version: "1.0"
---

# skillsaw Maintenance

You are performing maintenance on the **skillsaw** linter. Your goal is to ensure
skillsaw stays current with upstream specifications and continues to pass all tests.

## Step 1: Analyze upstream specs for changes

Fetch and review the current versions of:

1. **agentskills.io specification** at https://agentskills.io/specification
   - Check for new required/optional frontmatter fields in SKILL.md
   - Check for changes to naming rules, directory structure, or evals format
   - Compare against what skillsaw currently validates in `src/skillsaw/rules/builtin/agentskills.py`

2. **Claude Code plugin format** at https://docs.claude.com/en/docs/claude-code/plugins-reference
   - Check for new required fields in plugin.json
   - Check for new command format requirements
   - Check for structural changes to plugin layout
   - Compare against `src/skillsaw/rules/builtin/plugin_structure.py` and `command_format.py`

3. **Claude Code marketplace format** at https://docs.claude.com/en/docs/claude-code/plugin-marketplaces
   - Check for new marketplace.json requirements
   - Check for changes to plugin registration or discovery
   - Compare against `src/skillsaw/rules/builtin/marketplace.py`

4. **Claude Code hooks, MCP, agents, skills** formats
   - Hooks: https://docs.claude.com/en/docs/claude-code/hooks
   - MCP servers: https://docs.claude.com/en/docs/claude-code/mcp-servers
   - Skills and agents: https://docs.claude.com/en/docs/claude-code/skills
   - Review current docs for any format changes
   - Compare against the corresponding rule files in `src/skillsaw/rules/builtin/`

## Step 2: Identify gaps

For each spec change found, determine:
- Is there an existing rule that covers it? If so, does it need updating?
- Is a new rule needed? If so, what should it check and what severity?
- Would the change break backward compatibility? If so, how to handle it.

## Step 3: Check existing PRs

Use `gh pr list --state open` to find all open PRs in this repo.
For each open PR:
- Check if CI is passing (`gh pr checks`)
- Review any pending review comments (`gh pr view --comments`)
- If there are failing checks, investigate and fix them
- If there is reviewer feedback, address it

## Step 4: Implement fixes

For each gap identified in Step 2, create a separate PR:
- Create a new branch from main for the fix
- Implement the rule change or addition
- Write tests for any new or changed rules
- Run the full test suite: `pytest tests/ -v`
- Run formatting: `black src/ tests/`
- Test against ai-helpers: clone `openshift-eng/ai-helpers`, run `skillsaw` against it, ensure exit 0
- Open a PR with a clear title and description of what changed and why

## Step 5: Validate backward compatibility

Before finalizing any change:
- Ensure `skillsaw` still passes clean on `openshift-eng/ai-helpers` with default config
  (agentskills rules are disabled in their config)
- Ensure no existing tests break
- New rules should default to `enabled: auto` or `enabled: false` — never force-enable
  a new rule that could break existing users

## Important constraints

- Never introduce breaking changes to the config format
- The `claudelint` CLI shim and `from claudelint import ...` must continue working
- Config discovery must continue finding `.claudelint.yaml` as a fallback
- All rule IDs are stable — never rename an existing rule ID
