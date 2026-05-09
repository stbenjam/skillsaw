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

Keep your skills sharp. A configurable linter, scaffolding tool, doc generator, and CI companion for [agentskills.io](https://agentskills.io) skills, [Claude Code](https://docs.claude.com/en/docs/claude-code) [plugins](https://docs.claude.com/en/docs/claude-code/plugins), and [plugin marketplaces](https://docs.claude.com/en/docs/claude-code/plugin-marketplaces).

> Formerly named `claudelint`. If you're migrating, see [Migrating from claudelint](#migrating-from-claudelint).

</td>
</tr></table>

## Features

- 🧠 **Content Intelligence** — More than a dozen rules that analyze instruction file quality using attention research and prompt engineering best practices. Detects [weak language](#content-intelligence), [tautological instructions](https://arxiv.org/abs/2407.01906), [attention dead zones](https://arxiv.org/abs/2307.03172), embedded secrets, deprecated references, contradictions, and more
- 🔧 **LLM-Powered Autofix** — Fix content violations automatically with any LLM via LiteLLM. Parallel processing, scoped re-linting, per-file rollback on regression, and dry-run preview — all in one command: `skillsaw lint --fix --llm`
- 🔍 **Context-Aware** — Automatically detects agentskills repos, single plugins, marketplaces, and instruction file formats (CLAUDE.md, AGENTS.md, Cursor, Copilot, Gemini, Kiro) — enables the right rules without configuration
- 📐 **40+ Rules** — Validates skill format, plugin structure, metadata, command format, cross-file consistency, context budget, and instruction quality
- 🏗️ **Scaffolding** — Initialize marketplaces and add plugins, skills, commands, agents, and hooks with `skillsaw add`
- 📝 **Doc Generation** — Generate HTML or Markdown documentation for your plugins and skills with `skillsaw docs`
- 🔌 **Extensible** — Load custom rules from Python files, define custom banned patterns, configure per-rule thresholds
- 🤖 **CI-Ready** — GitHub Action posts inline PR comments with automatic deduplication and thread resolution
- ⚡ **Version-Gated** — New rules are gated behind config versions so existing users are never surprised on upgrade

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
- [Autofixing](#autofixing)
  - [Deterministic Fixes (`--fix`)](#deterministic-fixes---fix)
  - [LLM-Powered Fixes (`--fix --llm`)](#llm-powered-fixes---fix---llm)
- [Custom Rules](#custom-rules)
- [Scaffolding](#scaffolding)
  - [Initialize a Marketplace](#initialize-a-marketplace)
  - [Add Components](#add-components)
  - [Context Detection](#context-detection)
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

# Fix structural issues automatically
skillsaw lint --fix

# Fix content quality issues with an LLM
skillsaw lint --fix --llm

# Preview LLM fixes without writing
skillsaw lint --fix --llm --dry-run

# Verbose output (includes info-level findings)
skillsaw -v

# Strict mode (warnings become errors)
skillsaw --strict

# Generate default config
skillsaw init

# List all rules with fix support info
skillsaw list-rules

# Generate plugin/skill documentation
skillsaw docs

# Scaffold a new marketplace, plugin, or skill
skillsaw add marketplace
skillsaw add plugin my-plugin
skillsaw add skill my-skill
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
skillsaw init
```

This creates a config file with all builtin rules, their defaults, and
descriptions. Edit it to enable, disable, or customize rules for your project.
See [`.skillsaw.yaml.example`](.skillsaw.yaml.example) for a complete example.

## Builtin Rules

<!-- BEGIN GENERATED RULES -->

### agentskills.io

These rules validate skills against the [agentskills.io specification](https://agentskills.io/specification). They auto-enable for agentskills repos, single plugins, and marketplaces whenever skills are detected.

| Rule ID | Description | Default Severity | Autofix |
|---------|-------------|------------------|---------|
| `agentskill-valid` | SKILL.md must have valid frontmatter with name and description | error (auto) | auto, llm |
| `agentskill-name` | Skill name must be lowercase with hyphens and match directory name | error (auto) | auto |
| `agentskill-description` | Skill description should be meaningful and within length limits | warning (auto) | - |
| `agentskill-structure` | Skill directories should only contain recognized subdirectories (stricter than spec) | warning (disabled) | - |
| `agentskill-evals` | Validate evals/evals.json format when present | error (auto) | - |
| `agentskill-evals-required` | Require evals/evals.json for each skill (opt-in) | error (disabled) | - |

**`agentskill-structure` parameters:**

| Parameter | Description | Default |
|-----------|-------------|---------|
| `allowed_dirs` | Directory names allowed in the skill root | `["assets", "evals", "references", "scripts"]` |

### Plugin Structure

| Rule ID | Description | Default Severity | Autofix |
|---------|-------------|------------------|---------|
| `plugin-json-required` | Plugin must have .claude-plugin/plugin.json | error (auto) | - |
| `plugin-json-valid` | Plugin.json must be valid JSON with required fields | error (auto) | - |
| `plugin-naming` | Plugin names should use kebab-case | warning (auto) | - |
| `plugin-readme` | Plugin should have a README.md file | warning (auto) | llm |

**`plugin-json-valid` parameters:**

| Parameter | Description | Default |
|-----------|-------------|---------|
| `recommended-fields` | Fields that trigger a warning if missing from plugin.json | `["description", "version", "author"]` |

### Command Format

| Rule ID | Description | Default Severity | Autofix |
|---------|-------------|------------------|---------|
| `command-naming` | Command files should use kebab-case naming | warning | auto |
| `command-frontmatter` | Command files must have valid frontmatter with description | error | auto |
| `command-sections` | Command files should have Name, Synopsis, Description, and Implementation sections | warning (disabled) | - |
| `command-name-format` | Command Name section should be 'plugin-name:command-name' | warning (disabled) | - |

### Marketplace

| Rule ID | Description | Default Severity | Autofix |
|---------|-------------|------------------|---------|
| `marketplace-json-valid` | Marketplace.json must be valid JSON with required fields | error (auto) | - |
| `marketplace-registration` | Plugins must be registered in marketplace.json | error (auto) | auto |

### Skills, Agents, Hooks

| Rule ID | Description | Default Severity | Autofix |
|---------|-------------|------------------|---------|
| `skill-frontmatter` | SKILL.md files should have frontmatter with name and description | warning | auto |
| `agent-frontmatter` | Agent files must have valid frontmatter with name and description | error | auto |
| `hooks-json-valid` | hooks.json must be valid JSON with proper hook configuration structure | error | - |

### MCP (Model Context Protocol)

| Rule ID | Description | Default Severity | Autofix |
|---------|-------------|------------------|---------|
| `mcp-valid-json` | MCP configuration must be valid JSON with proper mcpServers structure | error | - |
| `mcp-prohibited` | Plugins should not enable non-allowlisted MCP servers | error (disabled) | - |

**`mcp-prohibited` parameters:**

| Parameter | Description | Default |
|-----------|-------------|---------|
| `allowlist` | MCP server names that are permitted | `[]` |

### Rules Directory

| Rule ID | Description | Default Severity | Autofix |
|---------|-------------|------------------|---------|
| `rules-valid` | .claude/rules/ files must be markdown with valid optional paths frontmatter | error (auto) | - |

### Openclaw

Validates `metadata.openclaw` in SKILL.md frontmatter against the [openclaw spec](https://docs.openclaw.ai/tools/skills). Only fires when `metadata.openclaw` is present.

| Rule ID | Description | Default Severity | Autofix |
|---------|-------------|------------------|---------|
| `openclaw-metadata` | Validate metadata.openclaw fields against the openclaw spec | warning (auto) | - |

### Instruction Files

Validates AI coding assistant instruction files (AGENTS.md, CLAUDE.md, GEMINI.md) at the repository root. Checks encoding, non-emptiness, and that `@import` references resolve to existing files. Disabled by default.

| Rule ID | Description | Default Severity | Autofix |
|---------|-------------|------------------|---------|
| `instruction-file-valid` | Instruction files (AGENTS.md, CLAUDE.md, GEMINI.md) must be valid and non-empty | warning (auto) | - |
| `instruction-imports-valid` | Import references (@path) in CLAUDE.md and GEMINI.md must point to existing files | warning (auto) | - |

### Context Budget

Warns when instruction and configuration files exceed recommended token limits. Uses a `len(text) / 4` approximation for token counting. Supports per-category `warn` and `error` thresholds. Disabled by default.

| Rule ID | Description | Default Severity | Autofix |
|---------|-------------|------------------|---------|
| `context-budget` | Warn when instruction or config files exceed recommended token limits | warning (auto) | - |

**`context-budget` parameters:**

| Parameter | Description | Default |
|-----------|-------------|---------|
| `limits` | Token limits per file category (int for warn-only, or {warn, error} dict) | `{"agents-md": {"warn": 6000, "error": 12000}, "claude-md": {"warn": 6000, "error": 12000}, "gemini-md": {"warn": 6000, "error": 12000}, "instruction": {"warn": 4000, "error": 8000}, "skill": {"warn": 3000, "error": 6000}, "command": {"warn": 2000, "error": 4000}, "agent": {"warn": 2000, "error": 4000}, "rule": {"warn": 2000, "error": 4000}}` |

### Content Intelligence

14 rules that go beyond structural validation to analyze the *quality* of instruction files. Built on attention research ([lost-in-the-middle](https://arxiv.org/abs/2307.03172), [instruction-following limits](https://openreview.net/forum?id=R6q67CDBCH)) and prompt engineering best practices. All support LLM-powered fixes via `--fix --llm`. See [docs/designs/content-rules-research.md](docs/designs/content-rules-research.md) for the full research basis behind each rule.

| Rule ID | Description | Default Severity | Autofix |
|---------|-------------|------------------|---------|
| `content-weak-language` | Detect hedging, vague, and non-actionable language in instruction files | warning (auto) | llm |
| `content-tautological` | Detect tautological instructions that the model already follows by default | warning (auto) | llm |
| `content-critical-position` | Detect critical instructions in the middle of files where LLM attention is lowest | warning (auto) | llm |
| `content-redundant-with-tooling` | Detect instructions that duplicate .editorconfig, ESLint, Prettier, or tsconfig settings | warning (auto) | llm |
| `content-instruction-budget` | Check if total instruction count across all files exceeds LLM instruction budget (~150) | warning (auto) | llm |
| `content-negative-only` | Detect prohibitions without a positive alternative (agent has no path forward) | warning (auto) | llm |
| `content-section-length` | Warn about markdown sections longer than ~500 tokens | info (auto) | llm |
| `content-contradiction` | Detect likely contradictions within instruction files using keyword-pair heuristics | warning (auto) | llm |
| `content-hook-candidate` | Detect instructions that should be automated as hooks instead of prose instructions | info (auto) | llm |
| `content-actionability-score` | Score instruction files on actionability (verb density, commands, file references) | info (auto) | llm |
| `content-cognitive-chunks` | Check that instruction files are organized into cognitive chunks with headings | info (auto) | llm |
| `content-embedded-secrets` | Detect potential API keys, tokens, and passwords in instruction files | error (auto) | llm |
| `content-banned-references` | Detect banned or deprecated model names, APIs, and custom patterns | warning (auto) | llm |
| `content-inconsistent-terminology` | Detect inconsistent terminology across instruction files (e.g., mixing 'directory' and 'folder') | info (auto) | llm |

**`content-section-length` parameters:**

| Parameter | Description | Default |
|-----------|-------------|---------|
| `max-tokens` | Maximum estimated tokens per section before triggering a warning | `500` |

**`content-banned-references` parameters:**

| Parameter | Description | Default |
|-----------|-------------|---------|
| `banned` | Additional banned patterns as list of {pattern, message} dicts | `[]` |
| `skip-builtins` | Disable built-in deprecated model/API checks | `false` |

<!-- END GENERATED RULES -->

## Autofixing

skillsaw supports two levels of autofixing — deterministic fixes for structural issues and LLM-powered fixes for content quality. Rules declare which fix type they support (see the **Autofix** column in the rules tables above).

### Deterministic Fixes (`--fix`)

Safe, pattern-based fixes that run instantly without any external dependencies:

```bash
skillsaw lint --fix              # Apply safe structural fixes
```

Examples: adding missing frontmatter, renaming files to kebab-case, registering unregistered plugins in marketplace.json, fixing skill names to match directory names. These are marked **SAFE** confidence and applied automatically.

### LLM-Powered Fixes (`--fix --llm`)

All content intelligence rules support LLM-powered fixes. The LLM reads your instruction files, rewrites violations, and re-lints in a loop until the file is clean — or rolls back if it made things worse.

```bash
# Fix content violations with an LLM (any LiteLLM-compatible model)
skillsaw lint --fix --llm

# Preview what would change without writing to disk
skillsaw lint --fix --llm --dry-run

# Use a specific model (OpenAI, Anthropic, Vertex AI, local, etc.)
skillsaw lint --fix --llm --model vertex_ai/claude-sonnet-4-6
skillsaw lint --fix --llm --model openrouter/minimax/minimax-m1
```

**How it works:**

1. skillsaw lints your repo and groups violations by file
2. Each file is sent to an LLM agent with 5 scoped tools: `read_file`, `write_file`, `replace_section`, `lint` (re-runs skillsaw), and `diff`
3. The LLM iteratively edits the file and re-lints until violations are resolved
4. After the LLM finishes, skillsaw compares violation counts — if a file got worse, it's rolled back to the original
5. Files are processed in parallel with a live progress bar showing ETA

The LLM never has access to arbitrary shell commands — it can only read, edit, lint, and diff within your repo. Use `--dry-run` to review all proposed changes as unified diffs before committing to them.

Check `skillsaw list-rules` to see which rules support `auto`, `llm`, or both fix types.

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

## Scaffolding

`skillsaw add` scaffolds marketplaces, plugins, and components with best-practice structure, CI, and branding out of the box.

### Initialize a Marketplace

```bash
# Interactive (prompts for name, owner, colors)
skillsaw add marketplace

# Non-interactive
skillsaw add marketplace --name my-plugins --owner myuser --color-scheme ocean-blue
```

This creates the full marketplace structure: `marketplace.json`, `settings.json`, GitHub Pages site, GitHub Actions CI, Makefile, and an example plugin.

### Add Components

```bash
# Add a plugin to a marketplace
skillsaw add plugin my-plugin

# Add a skill, command, agent, or hook
skillsaw add skill my-skill
skillsaw add command greet
skillsaw add agent helper
skillsaw add hook PreToolUse
```

### Context Detection

skillsaw automatically detects your repo type and places files in the right location:

- **Marketplace** — components go under `plugins/<name>/`
- **Single-plugin repo** — components go in the repo root
- **`.claude/` repo** — components go under `.claude/`

In a marketplace with multiple plugins, specify `--plugin <name>` or skillsaw will prompt interactively.

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
