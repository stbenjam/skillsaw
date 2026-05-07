[![PyPI version](https://badge.fury.io/py/skillsaw.svg)](https://badge.fury.io/py/skillsaw)
[![PyPI Downloads](https://img.shields.io/pypi/dm/skillsaw)](https://pypi.org/project/skillsaw/)
[![Tests](https://github.com/stbenjam/skillsaw/workflows/Tests/badge.svg)](https://github.com/stbenjam/skillsaw/actions/workflows/test.yml)
[![codecov](https://codecov.io/gh/stbenjam/skillsaw/branch/main/graph/badge.svg)](https://codecov.io/gh/stbenjam/skillsaw)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python Versions](https://img.shields.io/pypi/pyversions/skillsaw.svg)](https://pypi.org/project/skillsaw/)

# skillsaw

A configurable, rule-based linter for [agentskills.io](https://agentskills.io) skills, [Claude Code](https://docs.claude.com/en/docs/claude-code) [plugins](https://docs.claude.com/en/docs/claude-code/plugins), and [plugin marketplaces](https://docs.claude.com/en/docs/claude-code/plugin-marketplaces).

> **Note:** This project was formerly named `claudelint`. If you're migrating, see [Migrating from claudelint](#migrating-from-claudelint).

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

<!-- BEGIN GENERATED RULES -->

### agentskills.io

These rules validate skills against the [agentskills.io specification](https://agentskills.io/specification). They auto-enable for agentskills repos, single plugins, and marketplaces whenever skills are detected.

| Rule ID | Description | Default Severity |
|---------|-------------|------------------|
| `agentskill-valid` | SKILL.md must have valid frontmatter with name and description | error (auto) |
| `agentskill-name` | Skill name must be lowercase with hyphens and match directory name | error (auto) |
| `agentskill-description` | Skill description should be meaningful and within length limits | warning (auto) |
| `agentskill-structure` | Skill directories should only contain recognized subdirectories (stricter than spec) | warning (disabled) |
| `agentskill-evals` | Validate evals/evals.json format when present | warning (auto) |
| `agentskill-evals-required` | Require evals/evals.json for each skill (opt-in) | warning (disabled) |

**`agentskill-structure` parameters:**

| Parameter | Description | Default |
|-----------|-------------|---------|
| `allowed_dirs` | Directory names allowed in the skill root | `["scripts", "references", "assets", "evals"]` |

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
