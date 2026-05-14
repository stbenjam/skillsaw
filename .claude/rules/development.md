## CRITICAL: Always run `make update` before making a PR

`make update` regenerates all generated files: README rule docs, example config,
and `.claude/` from `.apm/`. PRs that skip this step will have stale docs. Run it
every time, no exceptions.

# Development Rules

skillsaw is a configurable, rule-based linter for agentskills.io skills,
Claude Code plugins, and plugin marketplaces.

## Backward Compatibility

- Never break existing linting for users of skillsaw or the older claudelint shim.
- The `claudelint` CLI shim and `from claudelint import ...` must continue working.
- Config discovery must continue finding `.claudelint.yaml` as a fallback.
- All rule IDs are stable — never rename an existing rule ID.
- New rules default to `enabled: auto` or `enabled: false` — never force-enable
  a new rule that could break existing users.

## Pre-PR Checklist

1. `make test` — run the full test suite.
2. `make lint` — check formatting (or `make format` to fix).
3. Bump version via `scripts/bump-version.sh`.
4. `make update` — regenerate all generated files (must come after version bump).
5. Test against `openshift-eng/ai-helpers`: clone it, run `skillsaw`, ensure exit 0.

## Writing Linter Rules

Rules MUST:

1. **Use the lint tree for file discovery** — call
   `context.lint_tree.find(NodeType)`, never `glob`, `rglob`, or `os.walk`.
2. **Report line numbers** on every violation traceable to a specific line.
   An approximate line is better than no line.
3. **Use `read_yaml_commented()`** (from `utils.py`) for YAML — never
   `yaml.safe_load()` or `read_yaml()`. It returns ruamel.yaml objects that
   preserve line numbers.
4. **Use `commented_key_line(node, key)` / `commented_item_line(node, index)`**
   to extract 1-based line numbers from ruamel data structures.
5. **Never fabricate line numbers** — if a field is missing, omit the line.
   Never hardcode `line=1`.
6. **Declare `repo_types`** to control when `enabled: auto` fires.
7. **Declare `config_schema`** when the rule accepts parameters.

JSON files are exempt from line number requirements — the `json` module does
not preserve them. File-level reporting is acceptable for JSON rules.
