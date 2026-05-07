---
description: Development guidelines and architecture overview for skillsaw
---

# skillsaw Development Guidelines

skillsaw is a configurable, rule-based linter for agentskills.io skills,
Claude Code plugins, and plugin marketplaces.

## Key Principles

- All changes must be backward compatible. Never break existing linting
  for users of skillsaw or the older claudelint shim.
- Test every change against openshift-eng/ai-helpers in default config.
  It must pass clean (exit 0) with agentskills rules disabled.
- Run the full test suite (`pytest tests/ -v`) before committing.
- Format with `black src/ tests/` before committing.

## Architecture

- `src/skillsaw/context.py` — repo type detection (SINGLE_PLUGIN, MARKETPLACE, AGENTSKILLS, UNKNOWN)
- `src/skillsaw/config.py` — config loading, rule enabling logic, `auto` with `repo_types`
- `src/skillsaw/rule.py` — base Rule class with `repo_types` class attribute
- `src/skillsaw/linter.py` — orchestration, loads builtin + custom rules
- `src/skillsaw/rules/builtin/` — all builtin rule implementations

## Rule Design

Rules declare `repo_types` to control when `enabled: auto` fires:
- `repo_types = {RepositoryType.MARKETPLACE}` — marketplace only
- `repo_types = {RepositoryType.AGENTSKILLS, RepositoryType.SINGLE_PLUGIN, RepositoryType.MARKETPLACE}` — wherever skills exist
- `repo_types = None` — always (default)

## Version Bumping

Use `scripts/bump-version.sh` to bump the version. It updates both
pyproject.toml and src/skillsaw/__init__.py. Pass a specific version
as an argument, or omit to auto-increment the patch version.
