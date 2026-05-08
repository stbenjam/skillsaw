[![PyPI version](https://badge.fury.io/py/skillsaw.svg)](https://badge.fury.io/py/skillsaw)
[![PyPI Downloads](https://img.shields.io/pypi/dm/skillsaw)](https://pypi.org/project/skillsaw/)
[![Tests](https://github.com/stbenjam/skillsaw/workflows/Tests/badge.svg)](https://github.com/stbenjam/skillsaw/actions/workflows/test.yml)
[![codecov](https://codecov.io/gh/stbenjam/skillsaw/branch/main/graph/badge.svg)](https://codecov.io/gh/stbenjam/skillsaw)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python Versions](https://img.shields.io/pypi/pyversions/skillsaw.svg)](https://pypi.org/project/skillsaw/)

<table><tr>
<td width="200" valign="top"><img src="https://raw.githubusercontent.com/stbenjam/skillsaw/main/images/logo.png" alt="skillsaw logo" width="200"></td>
<td valign="top">

### skillsaw

Lint your skills before they cut someone. A configurable linter, doc generator, and CI companion for [agentskills.io](https://agentskills.io) skills, [Claude Code](https://docs.claude.com/en/docs/claude-code) [plugins](https://docs.claude.com/en/docs/claude-code/plugins), and [plugin marketplaces](https://docs.claude.com/en/docs/claude-code/plugin-marketplaces).

> Formerly named `claudelint`. If you're migrating, see [Migrating from claudelint](#migrating-from-claudelint).

</td>
</tr></table>

## Features

- 🔍 **Context-Aware** — Automatically detects agentskills repos, single plugins, and marketplaces and enables the right rules
- 📐 **Rule-Based** — Enable/disable individual rules with configurable severity levels
- 📝 **Doc Generation** — Generate HTML or Markdown documentation for your plugins and skills with `skillsaw docs`
- 🔌 **Extensible** — Load custom rules from Python files
- ✅ **Comprehensive** — Validates skill format, plugin structure, metadata, command format, and cross-file consistency
- 🤖 **CI-Ready** — GitHub Action posts inline PR comments with automatic deduplication and thread resolution
- 🐳 **Containerized** — Run via Docker for consistent, isolated linting
- ⚡ **Fast** — Efficient validation with clear, actionable output

## Table of Contents

<!-- BEGIN GENERATED TOC -->

- [Features](#features)
- [Quick Start](#quick-start)
- [Installation](#installation)
  - [Via uvx (easiest, no install required)](#via-uvx-easiest-no-install-required)
  - [Via pip](#via-pip)
  - [From source](#from-source)
  - [Using Docker](#using-docker)
  - [GitHub Action](#github-action)
- [Repository Types](#repository-types)
  - [agentskills.io Skills](#agentskillsio-skills)
  - [Single Plugin](#single-plugin)
  - [Marketplace (Multiple Plugins)](#marketplace-multiple-plugins)
- [Configuration](#configuration)
- [Builtin Rules](#builtin-rules)
- [Custom Rules](#custom-rules)
- [Documentation Generation](#documentation-generation)
- [Exit Codes](#exit-codes)
- [Example Output](#example-output)
- [Migrating from claudelint](#migrating-from-claudelint)
  - [Removed rules](#removed-rules)
- [Development](#development)
- [Contributing](#contributing)
- [License](#license)
- [See Also](#see-also)
- [Support](#support)

<!-- END GENERATED TOC -->

## Quick Start

```bash
# Lint current directory (no install required)
uvx skillsaw

# Lint specific directory
skillsaw /path/to/skills

# Verbose output
skillsaw -v

# Strict mode (warnings as errors)
skillsaw --strict

# Generate default config
skillsaw --init

# List all available rules
skillsaw --list-rules

# Generate documentation
skillsaw docs
```

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

### GitHub Action

The built-in GitHub Action installs skillsaw, runs it, and posts violations as
inline PR comments with automatic deduplication. Fixed violations have their
comment threads resolved.

```yaml
name: Lint

on: [pull_request]

permissions:
  contents: read
  pull-requests: write

jobs:
  skillsaw:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: stbenjam/skillsaw@v0
        with:
          strict: true
```

#### Inputs

| Input | Description | Default |
|-------|-------------|---------|
| `path` | Path to lint | `.` |
| `version` | Specific skillsaw version to install | latest |
| `strict` | Treat warnings as errors | `false` |
| `verbose` | Include info-level violations | `false` |
| `token` | GitHub token for posting PR comments | `${{ github.token }}` |

#### Outputs

| Output | Description |
|--------|-------------|
| `exit-code` | skillsaw exit code (0=pass, 1=errors, 2=strict+warnings) |
| `errors` | Number of errors found |
| `warnings` | Number of warnings found |
| `report` | Full JSON report |

#### PR comment behavior

- Each violation gets its own inline comment on the relevant line or file
- Comments are deduplicated across re-runs using content fingerprinting
- When a violation is fixed, its comment thread is automatically resolved
- Comments with human replies are preserved

> **Permissions:** `contents: read` is required for checkout.
> `pull-requests: write` is required for posting comments.

## Repository Types

skillsaw automatically detects your repository structure:

### agentskills.io Skills

Standalone skill repositories following the [agentskills.io](https://agentskills.io) specification:

```
my-skill/
├── SKILL.md              # Required: metadata + instructions
├── scripts/              # Optional: executable code
├── references/           # Optional: documentation
├── assets/               # Optional: templates, resources
├── evals/                # Optional: evaluation tests
│   └── evals.json
└── <any-dir>/            # Arbitrary directories allowed per spec
```

Skill collections (multiple skills in subdirectories) are also supported:

```
skills-repo/
├── skill-one/
│   └── SKILL.md
└── skill-two/
    └── SKILL.md
```

Standard discovery paths (`.claude/skills/`, `.github/skills/`, `.agents/skills/`) are checked automatically.

### Single Plugin

```
my-plugin/
├── .claude-plugin/
│   └── plugin.json
├── commands/
│   └── my-command.md
├── skills/
│   └── my-skill/
│       └── SKILL.md
└── README.md
```

### Marketplace (Multiple Plugins)

skillsaw supports multiple marketplace structures per the [Claude Code specification](https://docs.claude.com/en/docs/claude-code/plugin-marketplaces):

#### Traditional Structure (plugins/ directory)
```
marketplace/
├── .claude-plugin/
│   └── marketplace.json
└── plugins/
    ├── plugin-one/
    │   ├── .claude-plugin/
    │   └── commands/
    └── plugin-two/
        ├── .claude-plugin/
        └── commands/
```

#### Flat Structure (root-level plugin)
```
marketplace/
├── .claude-plugin/
│   └── marketplace.json    # source: "./"
├── commands/
│   └── my-command.md
└── skills/
    └── my-skill/
```

#### Custom Paths and Mixed Structures

Plugins from `plugins/`, custom paths, and remote sources can coexist in one marketplace. Only local sources are validated.

## Configuration

Generate a default `.skillsaw.yaml` in your repository root:

```bash
skillsaw --init
```

This creates a config file with all builtin rules, their defaults, and
descriptions. Edit it to enable, disable, or customize rules for your project.
See [`.skillsaw.yaml.example`](.skillsaw.yaml.example) for a complete example.

## Builtin Rules

<!-- BEGIN GENERATED RULES -->

### agentskills.io

These rules validate skills against the [agentskills.io specification](https://agentskills.io/specification). They auto-enable for agentskills repos, single plugins, and marketplaces whenever skills are detected.

| Rule ID | Description | Default Severity |
|---------|-------------|------------------|
| `agentskill-valid` | SKILL.md must have valid frontmatter with name and description | error (auto) |
| `agentskill-name` | Skill name must be lowercase with hyphens and match directory name | error (auto) |
| `agentskill-description` | Skill description should be meaningful and within length limits | warning (auto) |
| `agentskill-structure` | Skill directories should only contain recognized subdirectories (stricter than spec) | warning (disabled) |
| `agentskill-evals` | Validate evals/evals.json format when present | error (auto) |
| `agentskill-evals-required` | Require evals/evals.json for each skill (opt-in) | error (disabled) |

**`agentskill-structure` parameters:**

| Parameter | Description | Default |
|-----------|-------------|---------|
| `allowed_dirs` | Directory names allowed in the skill root | `["assets", "evals", "references", "scripts"]` |

### Plugin Structure

| Rule ID | Description | Default Severity |
|---------|-------------|------------------|
| `plugin-json-required` | Plugin must have .claude-plugin/plugin.json | error (auto) |
| `plugin-json-valid` | Plugin.json must be valid JSON with required fields | error (auto) |
| `plugin-naming` | Plugin names should use kebab-case | warning (auto) |
| `plugin-readme` | Plugin should have a README.md file | warning (auto) |

**`plugin-json-valid` parameters:**

| Parameter | Description | Default |
|-----------|-------------|---------|
| `recommended-fields` | Fields that trigger a warning if missing from plugin.json | `["description", "version", "author"]` |

### Command Format

| Rule ID | Description | Default Severity |
|---------|-------------|------------------|
| `command-naming` | Command files should use kebab-case naming | warning |
| `command-frontmatter` | Command files must have valid frontmatter with description | error |
| `command-sections` | Command files should have Name, Synopsis, Description, and Implementation sections | warning |
| `command-name-format` | Command Name section should be 'plugin-name:command-name' | warning |

### Marketplace

| Rule ID | Description | Default Severity |
|---------|-------------|------------------|
| `marketplace-json-valid` | Marketplace.json must be valid JSON with required fields | error (auto) |
| `marketplace-registration` | Plugins must be registered in marketplace.json | error (auto) |

### Skills, Agents, Hooks

| Rule ID | Description | Default Severity |
|---------|-------------|------------------|
| `skill-frontmatter` | SKILL.md files should have frontmatter with name and description | warning |
| `agent-frontmatter` | Agent files must have valid frontmatter with name and description | error |
| `hooks-json-valid` | hooks.json must be valid JSON with proper hook configuration structure | error |

### MCP (Model Context Protocol)

| Rule ID | Description | Default Severity |
|---------|-------------|------------------|
| `mcp-valid-json` | MCP configuration must be valid JSON with proper mcpServers structure | error |
| `mcp-prohibited` | Plugins should not enable non-allowlisted MCP servers | error (disabled) |

**`mcp-prohibited` parameters:**

| Parameter | Description | Default |
|-----------|-------------|---------|
| `allowlist` | MCP server names that are permitted | `[]` |

### Rules Directory

| Rule ID | Description | Default Severity |
|---------|-------------|------------------|
| `rules-valid` | .claude/rules/ files must be markdown with valid optional paths frontmatter | error (auto) |

### Openclaw

Validates `metadata.openclaw` in SKILL.md frontmatter against the [openclaw spec](https://docs.openclaw.ai/tools/skills). Only fires when `metadata.openclaw` is present.

| Rule ID | Description | Default Severity |
|---------|-------------|------------------|
| `openclaw-metadata` | Validate metadata.openclaw fields against the openclaw spec | warning (auto) |

<!-- END GENERATED RULES -->

## Custom Rules

Create custom validation rules by extending the `Rule` base class:

```python
from pathlib import Path
from typing import List
from skillsaw import Rule, RuleViolation, Severity, RepositoryContext

class NoTodoCommentsRule(Rule):
    @property
    def rule_id(self) -> str:
        return "no-todo-comments"

    @property
    def description(self) -> str:
        return "Command files should not contain TODO comments"

    def default_severity(self) -> Severity:
        return Severity.WARNING

    def check(self, context: RepositoryContext) -> List[RuleViolation]:
        violations = []
        for plugin_path in context.plugins:
            commands_dir = plugin_path / "commands"
            if not commands_dir.exists():
                continue
            for cmd_file in commands_dir.glob("*.md"):
                content = cmd_file.read_text()
                if "TODO" in content:
                    violations.append(
                        self.violation("Found TODO comment", file_path=cmd_file)
                    )
        return violations
```

Then reference it in `.skillsaw.yaml`:

```yaml
custom-rules:
  - ./my_custom_rules.py

rules:
  no-todo-comments:
    enabled: true
    severity: warning
```

## Documentation Generation

skillsaw can generate documentation for your plugins, skills, and marketplaces:

```bash
# Generate HTML docs (default)
skillsaw docs

# Generate Markdown
skillsaw docs --format markdown

# Write to a specific file
skillsaw docs --format markdown -o docs/README.md

# Write to a directory
skillsaw docs -o my-docs/

# Custom title
skillsaw docs --title "My Plugin Docs"
```

The generated documentation includes plugin metadata, command descriptions,
skill summaries, and configuration details extracted from your repository.

## Exit Codes

- `0` - Success (no errors, or warnings only in non-strict mode)
- `1` - Failure (errors found, or warnings in strict mode)

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

### Removed rules

The following rules from `claudelint` have been removed in `skillsaw`:

| Rule ID | Reason |
|---------|--------|
| `commands-dir-required` | Claude Code now treats `skills/` and `commands/` as the same mechanism; requiring a `commands/` directory is no longer meaningful |
| `commands-exist` | Same as above — plugins don't need to have commands |

If your `.skillsaw.yaml` references these rule IDs, `skillsaw` will emit a warning about the unknown rule.

## Development

```bash
# Run tests
pytest tests/ -v

# Format code
black src/ tests/

# Build Docker image
docker build -t skillsaw .
```

## Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

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
