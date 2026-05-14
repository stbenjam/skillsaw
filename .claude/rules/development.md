skillsaw is a configurable, rule-based linter for agentic contextual building blocks.

## Pre-push Checklist

CRITICAL: You MUST always run these steps before pushing changes.

1. Ensure branch is up to date with UPSTREAM (stbenjam/skillsaw) - check git
   remotes then merge upstream's main
2. `make test` — run the full test suite, and ensure all tests pass. Never
   assume a problem is pre-existing, remember the boyscout rule and fix it
   anyway.
3. `make lint` — check formatting (or `make format` to fix).
4. `make update` — regenerate all generated files (must come after version
   bump).
5. Test against `openshift-eng/ai-helpers`: clone it, run `skillsaw`, ensure
   exit 0.

## Post-PR Checklist

After opening a PR, continue monitoring for feedback from CodeRabbit, Gemini,
and stbenjam.  You may cease monitoring 20 minutes after pushing a PR. Address
valid feedback that comes in.

## New Linter Rules

- **EVERYTHING MUST BE PART OF THE PARSE TREE**
- **Rules should be configurable, when there are tuneable settings**
- **Never break existing rules for users of skillsaw**
- **New rules default to `enabled: auto` or `enabled: false`**: never force-enable
  a new rule that could break existing users.
- **Use the lint tree for discovery** — call `context.lint_tree.find(NodeType)`
- **Report line numbers** on every violation traceable to a specific line, except for whole-file based violations
- **Use `read_yaml_commented()`** (from `utils.py`) for YAML — never
  `yaml.safe_load()` or `read_yaml()`. It returns ruamel.yaml objects that
  preserve line numbers.
- **Use `commented_key_line(node, key)` / `commented_item_line(node, index)`**
   to extract 1-based line numbers from ruamel data structures.
- **Never fabricate line numbers** — if a field is missing, omit the line.
- **Declare `repo_types`** to control when `enabled: auto` fires.
- **Declare `config_schema`** when the rule accepts parameters.

JSON files are exempt from line number requirements — the `json` module does
not preserve them. File-level reporting is acceptable for JSON rules.
