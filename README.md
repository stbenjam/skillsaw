<table><tr>
<td width="200" valign="top"><img src="https://raw.githubusercontent.com/stbenjam/skillsaw/main/images/logo.png" alt="skillsaw logo" width="200"></td>
<td valign="top">

### skillsaw

Keep your skills sharp. 40+ rules catch weak language, contradictions, attention dead zones, and structural issues — then auto-fix them.

[![PyPI version](https://badge.fury.io/py/skillsaw.svg)](https://badge.fury.io/py/skillsaw) [![PyPI Downloads](https://img.shields.io/pypi/dm/skillsaw)](https://pypi.org/project/skillsaw/) [![Tests](https://github.com/stbenjam/skillsaw/workflows/Tests/badge.svg)](https://github.com/stbenjam/skillsaw/actions/workflows/test.yml) [![codecov](https://codecov.io/gh/stbenjam/skillsaw/branch/main/graph/badge.svg)](https://codecov.io/gh/stbenjam/skillsaw) [![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0) [![skillsaw grade](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstbenjam%2Fskillsaw%2Fmain%2F.skillsaw-badge.json)](https://skillsaw.org/)

</td>
</tr></table>

[![Watch the skillsaw onboarding demo](https://raw.githubusercontent.com/stbenjam/skillsaw/main/images/onboarding-demo.png)](https://asciinema.org/a/1259880)

<p align="center">▶️ <b><a href="https://asciinema.org/a/1259880">Easy onboarding with AI!</a></b> — watch an AI agent grade, fix, and configure a repo from scratch.</p>

---

**[Full documentation at skillsaw.org](https://skillsaw.org)** — supports Claude Code plugins, agentskills.io, CLAUDE.md, AGENTS.md, Cursor, Copilot, Gemini, Kiro, CodeRabbit, and more.

## Quick Start

No install required — run with `uvx skillsaw` (or [install](#installation)
it for repeated use).

```bash
# 1. See what skillsaw detects in your repo
skillsaw tree

# 2. Lint it (current directory by default — also accepts multiple
#    directories and/or SKILL.md files: skillsaw lint dir1/ dir2/SKILL.md)
skillsaw

# 3. Fix what you can automatically
skillsaw fix

# 4. Accept remaining violations as the baseline
skillsaw baseline

# Done — only new violations will fail from here on
skillsaw   # exit 0

# Curious why a rule fired (or didn't)?
skillsaw explain content-weak-language
```

For all commands and flags, see the [CLI Reference](https://skillsaw.org/cli/).

> [!TIP]
> **:sparkles: Onboard with AI** — let your coding agent handle the entire setup in one shot.
>
> **Claude Code:**
> ```bash
> claude plugin marketplace add stbenjam/skillsaw
> claude plugin install skillsaw@skillsaw-marketplace
> ```
> Then type `/skillsaw-onboard` — it installs skillsaw, lints your repo, autofixes what it can, walks you through manual fixes, sets up CI, and creates a baseline.
>
> **Other agents** — see the [Getting Started guide](https://skillsaw.org/getting-started/#onboard-with-ai).

## Installation

### Via uvx (easiest, no install required)

```bash
uvx skillsaw
uvx skillsaw /path/to/skills
```

### Via pip

```bash
pip install skillsaw
```

### From source

```bash
git clone https://github.com/stbenjam/skillsaw.git
cd skillsaw
pip install -e .
```

### Using Docker

```bash
docker pull ghcr.io/stbenjam/skillsaw:latest
docker run -v $(pwd):/workspace ghcr.io/stbenjam/skillsaw
```

See the [Getting Started guide](https://skillsaw.org/getting-started/) for
GitHub Actions and other installation options.

## What skillsaw checks

skillsaw automatically detects your repository structure. A repository can
match multiple types simultaneously.

Supported repository types include:

- [agentskills.io skills](https://skillsaw.org/repo-types/#agentskillsio-skills)
- [Single Claude Code plugins](https://skillsaw.org/repo-types/#single-plugin)
- [Claude Code plugin marketplaces](https://skillsaw.org/repo-types/#marketplace-multiple-plugins)
- [`.claude/` directories](https://skillsaw.org/repo-types/#claude-directory)
- [CodeRabbit configuration](https://skillsaw.org/rules/coderabbit/)
- [Promptfoo eval configs](https://skillsaw.org/rules/promptfoo/)
- [APM repositories](https://skillsaw.org/rules/apm/)

The built-in rules cover structural validation, content intelligence, context
budgets, supply-chain checks, settings, MCP configuration, hooks, commands,
skills, agents, and marketplace registration.

Browse the [Repository Types](https://skillsaw.org/repo-types/) and
[Builtin Rules](https://skillsaw.org/rules/) references for the full details.

## Configuration

Generate a default `.skillsaw.yaml` in your repository root:

```bash
skillsaw init
```

This creates a config file with all builtin rules, their defaults, and
descriptions. Edit it to enable, disable, or customize rules for your project.
See [`.skillsaw.yaml.example`](.skillsaw.yaml.example) for a complete example.

Common configuration topics:

- [Version pinning](https://skillsaw.org/configuration/#version-pinning)
- [Exclude patterns](https://skillsaw.org/configuration/#exclude-patterns)
- [Per-rule excludes](https://skillsaw.org/configuration/#per-rule-excludes)
- [Inline suppression](https://skillsaw.org/configuration/#inline-suppression)
- [Content paths](https://skillsaw.org/configuration/#content-paths)

## Baseline

When adopting skillsaw on an existing project, you may have many
pre-existing violations. The **baseline** feature lets you snapshot
current violations so that `skillsaw lint` only reports *new* ones —
existing violations are accepted and won't cause failures.

```bash
# Generate .skillsaw-baseline.json from current violations
skillsaw baseline

# Run lint without baseline filtering
skillsaw lint --no-baseline
```

The baseline matches violations by fingerprint, so it survives ordinary line
drift and reports stale entries when old violations are fixed. See the
[Baseline guide](https://skillsaw.org/baseline/) for matching behavior,
ratchet behavior, and refresh workflow.

## CI Integration

```yaml
# GitHub Actions
- uses: stbenjam/skillsaw@v0
  with:
    strict: true
```

```yaml
# GitLab CI — outputs Code Quality JSON for MR widgets
skillsaw:
  script:
    - pip install skillsaw==0.16.0
    - skillsaw lint --output gitlab:gl-code-quality-report.json .
  artifacts:
    reports:
      codequality: gl-code-quality-report.json
```

Output formats for `--format` / `--output`: `text`, `json`, `sarif`, `html`,
`code-climate`, and `gitlab`.

For PR review comments, the secure two-workflow pattern, plugins, custom
rules, and full configuration options, see the
[CI Integration guide](https://skillsaw.org/ci/).

## Pre-commit

skillsaw ships a [Pre-commit](https://pre-commit.com/) hook. Add this to your
repository's `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/stbenjam/skillsaw
    rev: v0.16.0  # or pin a full commit SHA
    hooks:
      - id: skillsaw
```

See the [Pre-commit guide](https://skillsaw.org/pre-commit/) for details.

## Quality Grade & Badge

Every lint run computes a letter grade (A+ through F) summarizing
repository quality, shown in the text summary and in the JSON report
under `summary.grade`.

Add the badge to your README:

```markdown
[![skillsaw grade](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2FOWNER%2FREPO%2Fmain%2F.skillsaw-badge.json)](https://skillsaw.org/)
```

Generate the badge data with:

```bash
skillsaw badge .
```

See [`skillsaw badge`](https://skillsaw.org/cli/#skillsaw-badge) for badge
generation options.

## Context Budget Report

`skillsaw context` prices your agent content in estimated context-window
tokens, split by when it's paid for: the **session-start tax** (instruction
files with `@`-imports resolved, unscoped rules, and the frontmatter
descriptions of skills, commands, and agents) versus content loaded **on
demand** (whole skill, command, and agent files when invoked; references
and prompts; rules and instructions scoped by `paths:`/`applyTo:` globs or
non-`alwaysApply` cursor rules when their paths match).

No harness reads every instruction file — Claude Code reads CLAUDE.md,
Gemini reads GEMINI.md or AGENTS.md, Copilot and Cursor read their own
files plus AGENTS.md — so the report breaks the session total down per
harness, and `--harness` narrows it to one:

```bash
skillsaw context                  # union report with per-harness totals
skillsaw context --harness claude # what a Claude Code session pays
skillsaw context --format json    # full data for CI or dashboards
```

Every item is checked against the same limits the [`context-budget`
rule](https://skillsaw.org/rules/context-budget/) enforces. The report
itself never fails a run — `context` observes, the `context-budget` rule
enforces.

## Supply Chain Protection

skillsaw is designed for repositories that execute AI-agent instructions,
plugins, hooks, and custom rules. For untrusted pull requests:

- Pin skillsaw to a specific version.
- Keep custom rules disabled unless you trust the source.
- Use the secure CI workflow when posting PR comments.
- Review hooks, MCP servers, and settings changes carefully.

See [Supply Chain Protection](https://skillsaw.org/supply-chain-protection/)
for the threat model and hardened CI patterns.

## Autofixing

skillsaw applies deterministic fixes for structural issues. Content-quality
violations that need judgment are fixed by coding agents (Claude Code, Cursor,
etc.) — the lint interface is familiar, and every violation points to
`skillsaw explain` which includes how-to-fix guidance.

```bash
skillsaw fix                     # Apply safe structural fixes
skillsaw fix --suggest           # Also apply suggested fixes
skillsaw fix --dry-run           # Preview safe fixes as colored diffs
skillsaw fix --suggest --dry-run # Preview safe + suggested fixes
```

See [Autofixing](https://skillsaw.org/autofixing/) for deterministic fix
confidence levels, agent workflows, and idempotency guarantees.

## Custom Rules and Plugins

Create custom validation rules by extending the `Rule` base class and
referencing them from `.skillsaw.yaml`:

```yaml
custom-rules:
  - ./my_custom_rules.py
```

To share rules across repositories, package them as a **rule plugin** — a
pip-installable package that registers rules through the `skillsaw.plugins`
entry point group.

Start with [Custom Rules](https://skillsaw.org/custom-rules/) for local checks
and [Rule Plugins](https://skillsaw.org/plugins/) for reusable distribution.

## Scaffolding

`skillsaw add` scaffolds marketplaces, plugins, and components with
best-practice structure, CI, and branding out of the box.

```bash
skillsaw add marketplace
skillsaw add plugin my-plugin
skillsaw add skill my-skill
skillsaw add command greet
skillsaw add agent helper
skillsaw add hook PreToolUse
```

See [Scaffolding](https://skillsaw.org/scaffolding/) for context detection,
marketplace layouts, and generated files.

## Documentation Generation

skillsaw can generate documentation for your plugins, skills, and marketplaces:

```bash
skillsaw docs
skillsaw docs --format markdown
skillsaw docs -o my-docs/
```

See the [CLI Reference](https://skillsaw.org/cli/#docs) for all documentation
generation options.

## Example Output

```
Linting: /path/to/skills-repo

Errors:
  ✗ ERROR [skills/my-skill/SKILL.md]: Name 'My Skill' must contain only lowercase letters, numbers, and hyphens
  ✗ ERROR [plugins/git/.claude-plugin/plugin.json]: Missing plugin.json

Warnings:
  ⚠ WARNING [skills/helper/SKILL.md]: Description exceeds 1024 characters (1087)
  ⚠ WARNING [plugins/utils]: Missing README.md (recommended)

Summary:
  Errors:   2
  Warnings: 2
```

## Migrating from claudelint

This project was renamed from `claudelint` to `skillsaw`. To migrate:

1. Update your package: `pip install skillsaw` (instead of `pip install claudelint`)
2. Rename `.claudelint.yaml` to `.skillsaw.yaml` (the old name is still discovered as a fallback)
3. Update CLI usage: `skillsaw` (instead of `claudelint`)
4. Update imports in custom rules: `from skillsaw import ...` (the old `from claudelint import ...` still works)

The `claudelint` command still works as a shim but prints a deprecation warning.

## Development

```bash
# Run tests
pytest tests/ -v

# Format code
black src/ tests/

# Build Docker image
docker build -t skillsaw .
```

See [DEVELOPMENT.md](DEVELOPMENT.md) for setup instructions.

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines and [DEVELOPMENT.md](DEVELOPMENT.md) for setup instructions.

## License

Apache 2.0 - See [LICENSE](LICENSE) for details.

## See Also

- [agentskills.io Specification](https://agentskills.io/specification)
- [Claude Code Documentation](https://docs.claude.com/en/docs/claude-code)
- [Claude Code Plugins Reference](https://docs.claude.com/en/docs/claude-code/plugins-reference)
- [AI Helpers Marketplace](https://github.com/openshift-eng/ai-helpers) - Example marketplace using skillsaw

## Support

- **Issues**: https://github.com/stbenjam/skillsaw/issues
- **Discussions**: https://github.com/stbenjam/skillsaw/discussions
