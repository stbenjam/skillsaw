---
description: Core development rules and backward compatibility requirements
---

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
3. `make update` — regenerate all generated files.
4. Bump version via `scripts/bump-version.sh`.
5. Test against `openshift-eng/ai-helpers`: clone it, run `skillsaw`, ensure exit 0.
