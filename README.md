[![PyPI version](https://badge.fury.io/py/skillsaw.svg)](https://badge.fury.io/py/skillsaw)
[![PyPI Downloads](https://img.shields.io/pypi/dm/skillsaw)](https://pypi.org/project/skillsaw/)
[![Tests](https://github.com/stbenjam/skillsaw/workflows/Tests/badge.svg)](https://github.com/stbenjam/skillsaw/actions/workflows/test.yml)
[![codecov](https://codecov.io/gh/stbenjam/skillsaw/branch/main/graph/badge.svg)](https://codecov.io/gh/stbenjam/skillsaw)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python Versions](https://img.shields.io/pypi/pyversions/skillsaw.svg)](https://pypi.org/project/skillsaw/)

# skillsaw

A configurable, rule-based linter for [agentskills.io](https://agentskills.io) skills, [Claude Code](https://docs.claude.com/en/docs/claude-code) [plugins](https://docs.claude.com/en/docs/claude-code/plugins), and [plugin marketplaces](https://docs.claude.com/en/docs/claude-code/plugin-marketplaces).

> **Note:** This project was formerly named `claudelint` and then `agentlint`. If you're migrating, see [Migrating from claudelint/agentlint](#migrating-from-claudelintagentlint).

## Features

- **Context-Aware** - Automatically detects agentskills repos, single plugins, and marketplaces
- **Rule-Based** - Enable/disable individual rules with configurable severity levels
- **Extensible** - Load custom rules from Python files
- **Comprehensive** - Validates skill format, plugin structure, metadata, command format, and more
- **Containerized** - Run via Docker for consistent, isolated linting
- **Fast** - Efficient validation with clear, actionable output

## Installation

### Via uvx (easiest - no install required)

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

## Quick Start

```bash
# Lint current directory
skillsaw

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
```

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
└── evals/                # Optional: evaluation tests
    └── evals.json
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

Create `.skillsaw.yaml` in your repository root:

```yaml
rules:
  # agentskills rules (auto-enabled when skills are detected)
  agentskill-valid:
    enabled: auto
    severity: error

  agentskill-name:
    enabled: auto
    severity: error

  # Plugin structure rules
  plugin-json-required:
    enabled: true
    severity: error

  # 'auto' enables only for relevant repo types
  marketplace-registration:
    enabled: auto
    severity: error

# Load custom rules
custom-rules:
  - ./my-custom-rules.py

# Exclude patterns
exclude:
  - "**/node_modules/**"
  - "**/.git/**"

# Treat warnings as errors
strict: false
```

### Generating Default Config

```bash
skillsaw --init
```

This creates `.skillsaw.yaml` with all builtin rules and their defaults.

## Builtin Rules

### agentskills.io

These rules validate skills against the [agentskills.io specification](https://agentskills.io/specification). They auto-enable for agentskills repos, single plugins, and marketplaces whenever skills are detected.

| Rule ID | Description | Default Severity |
|---------|-------------|------------------|
| `agentskill-valid` | SKILL.md must have valid frontmatter with name and description | error (auto) |
| `agentskill-name` | Skill name must be lowercase with hyphens and match directory name | error (auto) |
| `agentskill-description` | Skill description should be meaningful and within length limits | warning (auto) |
| `agentskill-structure` | Skill directories should only contain recognized subdirectories | warning (auto) |
| `agentskill-evals` | Validate evals/evals.json format when present | warning (auto) |
| `agentskill-evals-required` | Require evals/evals.json for each skill | warning (disabled) |

### Plugin Structure

| Rule ID | Description | Default Severity |
|---------|-------------|------------------|
| `plugin-json-required` | Plugin must have `.claude-plugin/plugin.json` | error |
| `plugin-json-valid` | Plugin.json must be valid with required fields | error |
| `plugin-naming` | Plugin names should use kebab-case | warning |
| `commands-dir-required` | Plugin should have a commands directory | warning (disabled) |
| `commands-exist` | Plugin should have at least one command file | info (disabled) |
| `plugin-readme` | Plugin should have a README.md file | warning |

### Command Format

| Rule ID | Description | Default Severity |
|---------|-------------|------------------|
| `command-naming` | Command files should use kebab-case | warning |
| `command-frontmatter` | Command files must have valid frontmatter | error |
| `command-sections` | Commands should have Name, Synopsis, Description, Implementation sections | warning |
| `command-name-format` | Command Name section should be `plugin:command` format | warning |

### Marketplace

| Rule ID | Description | Default Severity |
|---------|-------------|------------------|
| `marketplace-json-valid` | Marketplace.json must be valid JSON | error (auto) |
| `marketplace-registration` | Plugins must be registered in marketplace.json | error (auto) |

### Skills, Agents, Hooks

| Rule ID | Description | Default Severity |
|---------|-------------|------------------|
| `skill-frontmatter` | SKILL.md files should have frontmatter | warning |
| `agent-frontmatter` | Agent files must have valid frontmatter | error |
| `hooks-json-valid` | hooks.json must be valid with proper structure | error |

### MCP (Model Context Protocol)

| Rule ID | Description | Default Severity |
|---------|-------------|------------------|
| `mcp-valid-json` | MCP configuration must be valid JSON | error |
| `mcp-prohibited` | Plugins should not enable MCP servers | error (disabled) |

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

## CI/CD Integration

### GitHub Actions

```yaml
name: Lint Agent Skills

on: [pull_request, push]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: '3.x'

      - name: Install skillsaw
        run: pip install skillsaw

      - name: Run linter
        run: skillsaw --strict
```

### Docker

```bash
docker run -v $(pwd):/workspace ghcr.io/stbenjam/skillsaw --strict
```

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

## Migrating from claudelint/agentlint

This project was renamed from `claudelint` to `agentlint` and then to `skillsaw`. To migrate:

1. Update your package: `pip install skillsaw` (instead of `pip install agentlint` or `pip install claudelint`)
2. Rename config files: `.agentlint.yaml` or `.claudelint.yaml` to `.skillsaw.yaml` (the old names are still discovered as fallbacks)
3. Update CLI usage: `skillsaw` (instead of `agentlint` or `claudelint`)
4. Update imports in custom rules: `from skillsaw import ...` (the old `from agentlint import ...` and `from claudelint import ...` still work)

The `agentlint` and `claudelint` commands still work as shims but print deprecation warnings.

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
