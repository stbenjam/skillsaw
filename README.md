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

Keep your skills sharp. A linter with built-in content intelligence for [agentskills.io](https://agentskills.io) skills, [Claude Code](https://docs.claude.com/en/docs/claude-code) [plugins](https://docs.claude.com/en/docs/claude-code/plugins), and [plugin marketplaces](https://docs.claude.com/en/docs/claude-code/plugin-marketplaces). Analyzes instruction file quality using attention research, detects weak language and contradictions, and auto-fixes violations with any LLM.

</td>
</tr></table>

> Formerly named `claudelint`. If you're migrating, see [Migrating from claudelint](#migrating-from-claudelint).

## Features

- 🧠 **Content Intelligence** — [Research-backed](docs/designs/content-rules-research.md) rules that catch [weak language](#content-intelligence), [tautological instructions](https://arxiv.org/abs/2407.01906), [attention dead zones](https://arxiv.org/abs/2307.03172), embedded secrets, contradictions, and more
- 🔧 **LLM Autofix** — Fix violations with any LLM via `skillsaw fix --llm` — parallel processing, scoped re-lint, per-file rollback
- 🔍 **Context-Aware** — Auto-detects repo type and instruction formats (CLAUDE.md, AGENTS.md, Cursor, Copilot, Gemini, Kiro)
- 📐 **40+ Rules** — Validates structure, metadata, commands, cross-file consistency, context budget, and content quality
- 🏗️ **Scaffolding** — `skillsaw add` generates plugins, skills, commands, agents, and hooks
- 📝 **Docs** — `skillsaw docs` generates HTML or Markdown documentation
- 🔌 **Extensible** — Custom rules, banned patterns, per-rule thresholds
- 🤖 **CI-Ready** — GitHub Action with inline PR comments, deduplication, and thread resolution
- ⚡ **Version-Gated** — New rules gated behind config versions — no surprises on upgrade

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
  - [`.claude/` Directory](#claude-directory)
  - [CodeRabbit](#coderabbit)
  - [APM (Agent Package Manager)](#apm-agent-package-manager)
- [Configuration](#configuration)
  - [Version Pinning](#version-pinning)
  - [Exclude Patterns](#exclude-patterns)
  - [Per-Rule Excludes](#per-rule-excludes)
  - [Inline Suppression](#inline-suppression)
  - [Content Paths](#content-paths)
- [Builtin Rules](#builtin-rules)
- [Autofixing](#autofixing)
  - [Deterministic Fixes](#deterministic-fixes)
  - [LLM-Powered Fixes](#llm-powered-fixes)
  - [LLM Setup](#llm-setup)
- [Custom Rules](#custom-rules)
- [Scaffolding](#scaffolding)
  - [Initialize a Marketplace](#initialize-a-marketplace)
  - [Add Components](#add-components)
  - [Context Detection](#context-detection)
- [Lint Tree](#lint-tree)
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
skillsaw fix

# Fix content quality issues with an LLM
skillsaw fix --llm

# Preview LLM fixes without writing
skillsaw fix --llm --dry-run

# Verbose output (includes info-level findings)
skillsaw -v

# Strict mode (warnings become errors)
skillsaw --strict

# Generate default config
skillsaw init

# List all rules with fix support info
skillsaw list-rules

# View the lint tree (what skillsaw sees)
skillsaw tree

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

The GitHub Action installs skillsaw, runs it, and prints violations in the CI
log. A separate review action posts violations as inline PR comments with
automatic deduplication and thread resolution.

#### Basic usage (lint only)

```yaml
name: Lint

on: [pull_request]

permissions:
  contents: read

jobs:
  skillsaw:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: stbenjam/skillsaw@v0
        with:
          strict: true
```

#### With PR review comments

To post inline comments on PRs (including fork PRs), use the two-workflow
pattern. The lint workflow runs with read-only permissions and uploads the
report as an artifact. A second workflow triggers on completion and posts
comments with write permissions — without ever checking out untrusted code.

```yaml
# .github/workflows/lint.yml
name: Lint

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  skillsaw:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: stbenjam/skillsaw@v0
        with:
          strict: true
```

```yaml
# .github/workflows/lint-review.yml
name: Lint Review

on:
  workflow_run:
    workflows: ["Lint"]
    types: [completed]

jobs:
  review:
    if: github.event.workflow_run.event == 'pull_request'
    runs-on: ubuntu-latest
    permissions:
      pull-requests: write
    steps:
      - uses: actions/checkout@v5
      - uses: stbenjam/skillsaw/review@v0
```

#### Inputs

| Input | Description | Default |
|-------|-------------|---------|
| `path` | Path to lint | `.` |
| `version` | Specific skillsaw version to install | latest |
| `strict` | Treat warnings as errors | `false` |
| `verbose` | Include info-level violations | `false` |

#### Outputs

| Output | Description |
|--------|-------------|
| `exit-code` | skillsaw exit code (0=pass, 1=errors, 2=strict+warnings) |
| `errors` | Number of errors found |
| `warnings` | Number of warnings found |
| `report-file` | Path to JSON report file |

#### PR comment behavior

- Each violation gets its own inline comment on the relevant line or file
- Comments are deduplicated across re-runs using content fingerprinting
- When a violation is fixed, its comment thread is automatically resolved
- Comments with human replies are preserved

## Repository Types

skillsaw automatically detects your repository structure. A repository can match multiple types simultaneously (e.g. an agentskills repo that also has `.coderabbit.yaml`).

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

### `.claude/` Directory

Repositories with a `.claude/` directory containing commands, skills, hooks, agents, or rules. When APM is present, `.claude/` is treated as compiled output and this type is not detected.

### CodeRabbit

Repositories with a `.coderabbit.yaml` file. skillsaw validates the instruction fragments within the config.

### APM (Agent Package Manager)

Repositories with an `.apm/` directory or `apm.yml` file. APM manages dependencies and compiles instruction files for all supported agents (`.claude/`, `.cursor/rules/`, `.github/instructions/`, etc.). When APM is present it is the authoritative source — `.claude/` is treated as compiled output.

## Configuration

Generate a default `.skillsaw.yaml` in your repository root:

```bash
skillsaw init
```

This creates a config file with all builtin rules, their defaults, and
descriptions. Edit it to enable, disable, or customize rules for your project.
See [`.skillsaw.yaml.example`](.skillsaw.yaml.example) for a complete example.

### Version Pinning

The config file includes a `version` field set to the skillsaw version that
created it. New rules introduced after that version are automatically skipped
unless you bump the version or explicitly enable them. Repos **without** a
`.skillsaw.yaml` run all rules at the latest version — you get new rules
automatically but may occasionally fail after a skillsaw upgrade.

### Exclude Patterns

Skip files and directories using glob patterns:

```yaml
exclude:
  - "vendor/**"
  - "generated/**"
  - "node_modules/**"
```

By default, skillsaw excludes `**/template/**`, `**/templates/**`, and
`**/_template/**` directories. These defaults are replaced when you specify
your own `exclude` list.

Exclude patterns apply to **all** rules, including custom rules loaded via
`custom-rules`. Any violation whose file path matches an exclude pattern is
filtered out before results are reported.

### Per-Rule Excludes

Exclude specific files from a single rule using the `exclude` key in the
rule's config:

```yaml
rules:
  content-weak-language:
    enabled: true
    exclude:
      - "docs/legacy/**"
      - "CHANGELOG.md"
```

This is useful when a rule produces false positives on specific files but
you still want it enabled globally. Per-rule excludes use the same glob
syntax as global `exclude` patterns.

### Inline Suppression

Suppress specific rules on specific lines using HTML comment directives
directly in your markdown files:

```markdown
<!-- skillsaw-disable content-weak-language -->
This section intentionally uses informal language.
<!-- skillsaw-enable content-weak-language -->
```

Suppress a single line:

```markdown
<!-- skillsaw-disable-next-line content-tautological -->
Follow best practices for error handling.
```

Suppress multiple rules at once:

```markdown
<!-- skillsaw-disable content-weak-language, content-tautological -->
```

Re-enable all suppressed rules:

```markdown
<!-- skillsaw-enable -->
```

Multi-line HTML comments are also supported:

```markdown
<!--
    skillsaw-disable content-weak-language
-->
```

Inline suppression only affects rules that are already enabled. It cannot
be used to enable a normally disabled rule.

### Content Paths

By default, content intelligence rules only analyze recognized instruction
files (CLAUDE.md, AGENTS.md, `.cursor/rules/`, `.apm/instructions/`, etc.).
Use `content-paths` to extend coverage to any text files that contain
instructions for humans or AI agents — markdown, `.mdc`, `.txt`, or any
other format:

```yaml
content-paths:
  - "src/**/instructions/**/*.md"
  - ".cursor/rules/*.mdc"
  - "docs/runbooks/*.txt"
```

Matched files are analyzed by all content-\* rules and support LLM-powered
fixes via `skillsaw fix --llm`.

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

**`agentskill-valid` parameters:**

| Parameter | Description | Default |
|-----------|-------------|---------|
| `required-fields` | Additional frontmatter fields to require (name and description are always required) | `[]` |
| `required-metadata` | Keys that must be present inside the metadata mapping | `[]` |

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
| `skill-frontmatter` | SKILL.md files should have frontmatter with name and description | warning | auto, llm |
| `agent-frontmatter` | Agent files must have valid frontmatter with name and description | error | auto, llm |
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
| `limits` | Token limits per file category (int for warn-only, or {warn, error} dict) | `{"agents-md": {"warn": 6000, "error": 12000}, "claude-md": {"warn": 6000, "error": 12000}, "gemini-md": {"warn": 6000, "error": 12000}, "instruction": {"warn": 4000, "error": 8000}, "skill": {"warn": 3000, "error": 6000}, "command": {"warn": 2000, "error": 4000}, "agent": {"warn": 2000, "error": 4000}, "rule": {"warn": 2000, "error": 4000}, "skill-description": {"warn": 200, "error": 500}, "command-description": {"warn": 200, "error": 500}}` |

### Content Intelligence

Rules that go beyond structural validation to analyze the *quality* of instruction files. Built on attention research ([lost-in-the-middle](https://arxiv.org/abs/2307.03172), [instruction-following limits](https://openreview.net/forum?id=R6q67CDBCH)) and prompt engineering best practices. Most support LLM-powered fixes via `skillsaw fix --llm`. See [docs/designs/content-rules-research.md](docs/designs/content-rules-research.md) for the full research basis behind each rule.

| Rule ID | Description | Default Severity | Autofix |
|---------|-------------|------------------|---------|
| `content-weak-language` | Detect hedging, vague, and non-actionable language in instruction files | warning (auto) | llm |
| `content-tautological` | Detect tautological instructions that the model already follows by default | warning (auto) | llm |
| `content-critical-position` | Detect critical instructions in the middle of files where LLM attention is lowest | warning (auto) | llm |
| `content-redundant-with-tooling` | Detect instructions that duplicate .editorconfig, ESLint, Prettier, or tsconfig settings | warning (auto) | llm |
| `content-instruction-budget` | Check if instruction count in a file exceeds LLM instruction budget (~150) | warning (auto) | llm |
| `content-negative-only` | Detect prohibitions without a positive alternative (agent has no path forward) | warning (auto) | llm |
| `content-section-length` | Warn about markdown sections longer than ~500 tokens | info (auto) | llm |
| `content-contradiction` | Detect likely contradictions within instruction files using keyword-pair heuristics | warning (auto) | llm |
| `content-hook-candidate` | Detect instructions that should be automated as hooks instead of prose instructions | info (auto) | llm |
| `content-actionability-score` | Score instruction files on actionability (verb density, commands, file references) | info (auto) | llm |
| `content-cognitive-chunks` | Check that instruction files are organized into cognitive chunks with headings | info (auto) | llm |
| `content-embedded-secrets` | Detect potential API keys, tokens, and passwords in instruction files | error (auto) | llm |
| `content-banned-references` | Detect banned or deprecated model names, APIs, and custom patterns | warning (auto) | llm |
| `content-inconsistent-terminology` | Detect inconsistent terminology across instruction files (e.g., mixing 'directory' and 'folder') | info (auto) | llm |
| `content-broken-internal-reference` | Detect markdown links where the target file does not exist | warning (auto) | auto |
| `content-unlinked-internal-reference` | Detect bare path-like strings not wrapped in markdown link syntax | info (auto) | auto |
| `content-placeholder-text` | Detect TODO markers, bracket placeholders, and unfilled template text | warning (auto) | - |

**`content-critical-position` parameters:**

| Parameter | Description | Default |
|-----------|-------------|---------|
| `min-lines` | Minimum file length (in lines) before the rule activates | `50` |

**`content-section-length` parameters:**

| Parameter | Description | Default |
|-----------|-------------|---------|
| `max-tokens` | Maximum estimated tokens per section before triggering a warning | `500` |

**`content-banned-references` parameters:**

| Parameter | Description | Default |
|-----------|-------------|---------|
| `banned` | Additional banned patterns as list of {pattern, message} dicts | `[]` |
| `skip-builtins` | Disable built-in deprecated model/API checks | `false` |

**`content-unlinked-internal-reference` parameters:**

| Parameter | Description | Default |
|-----------|-------------|---------|
| `patterns` | Glob patterns for path-like strings to flag when unlinked | `["./**/*.*", "references/**/*.md"]` |

### CodeRabbit

Validates `.coderabbit.yaml` config files for YAML syntax. Instruction text fields (`reviews.instructions`, per-path instructions, per-tool instructions, `chat.instructions`) are automatically checked by the content-* rules above. Auto-enabled when `.coderabbit.yaml` is detected.

| Rule ID | Description | Default Severity | Autofix |
|---------|-------------|------------------|---------|
| `coderabbit-yaml-valid` | .coderabbit.yaml must be valid YAML | error (auto) | - |

### APM (Agent Package Manager)

Validates repositories using the [APM](https://github.com/microsoft/apm) directory layout (`.apm/`). Auto-enables when `.apm/` is detected.

| Rule ID | Description | Default Severity | Autofix |
|---------|-------------|------------------|---------|
| `apm-yaml-valid` | apm.yml must exist with valid YAML and required fields (name, version, description) | error (auto) | - |
| `apm-structure-valid` | .apm/ directory must contain skills/ or instructions/ with valid structure | warning (auto) | - |

<!-- END GENERATED RULES -->

## Autofixing

skillsaw supports two levels of autofixing — deterministic fixes for structural issues and LLM-powered fixes for content quality. Rules declare which fix type they support (see the **Autofix** column in the rules tables above).

### Deterministic Fixes

Safe, pattern-based fixes that run instantly without any external dependencies:

```bash
skillsaw fix                     # Apply safe structural fixes
skillsaw fix --suggest           # Also apply suggested fixes (e.g. stale references)
skillsaw fix --dry-run           # Preview safe fixes as colored diffs without writing
skillsaw fix --suggest --dry-run # Preview safe + suggested fixes
```

Examples: adding missing frontmatter, renaming files to kebab-case, registering unregistered plugins in marketplace.json, fixing skill names to match directory names. These are marked **SAFE** confidence and applied automatically.

Some fixes produce cascading changes — for example, renaming a skill name creates stale references in other files. These secondary fixes are marked **SUGGEST** confidence because simple name matching may replace occurrences that aren't actually skill name references. Use `--suggest --dry-run` to review these changes before applying them.

### LLM-Powered Fixes

Most content intelligence rules support LLM-powered fixes (see the **Autofix** column above). The LLM reads your instruction files, rewrites violations, and re-lints in a loop until the file is clean — or rolls back if it made things worse.

```bash
skillsaw fix --llm                          # Fix with default model
skillsaw fix --llm --model vertex_ai/claude-sonnet-4-6
skillsaw fix --llm --model openrouter/minimax/minimax-m1
skillsaw fix --llm --all                    # Include info-level violations
skillsaw fix --llm --workers 8              # Parallel workers (default: 4)
skillsaw fix --llm --max-iterations 10      # Max iterations per file
skillsaw fix --llm --dry-run                # Preview changes without writing
skillsaw fix --llm -y                       # Auto-apply without confirmation
```

**How it works:**

1. skillsaw lints your repo and groups violations by file
2. Each file is sent to an LLM agent with 5 scoped tools: `read_file`, `write_file`, `replace_section`, `lint` (re-runs skillsaw), and `diff`
3. The LLM iteratively edits the file and re-lints until violations are resolved
4. After the LLM finishes, skillsaw compares violation counts — if a file got worse, it's rolled back to the original
5. Files are processed in parallel with a live progress bar showing ETA

The LLM never has access to arbitrary shell commands — it can only read, edit, lint, and diff within your repo. Use `--dry-run` to review all proposed changes as unified diffs before committing to them.

Check `skillsaw list-rules` to see which rules support `auto`, `llm`, or both fix types.

> **Note:** `skillsaw lint --fix` is deprecated and will be removed in 1.0. Use `skillsaw fix` instead.

### LLM Setup

skillsaw uses [LiteLLM](https://docs.litellm.ai/docs/providers) under the hood, so any LiteLLM-compatible model works. Install the extras for your provider:

```bash
# pip
pip install 'skillsaw[llm]'       # Any LiteLLM-compatible model
pip install 'skillsaw[vertexai]'  # Vertex AI (includes google-cloud-aiplatform)
pip install 'skillsaw[bedrock]'   # AWS Bedrock (includes boto3)

# uvx (no install required)
uvx --with 'skillsaw[llm]' skillsaw fix --llm
uvx --with 'skillsaw[vertexai]' skillsaw fix --llm --model vertex_ai/claude-sonnet-4-6
```

Set the environment variables for your provider:

| Provider | Environment Variables |
|----------|----------------------|
| Anthropic | `ANTHROPIC_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| Vertex AI | `VERTEXAI_PROJECT`, `VERTEXAI_LOCATION` (+ `gcloud auth application-default login`) |
| AWS Bedrock | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION_NAME` |

You can also set `SKILLSAW_MODEL` to override the default model via environment variable, or `llm.model` in your `.skillsaw.yaml` config.

See the [LiteLLM provider documentation](https://docs.litellm.ai/docs/providers) for the full list of supported providers and their required environment variables.

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

## Lint Tree

`skillsaw tree` visualizes the typed lint tree — the internal data structure that all rules operate on. Every lintable entity (plugins, skills, commands, agents, instruction files, config files) is a typed node in the tree.

```bash
# View the lint tree
skillsaw tree

# View a specific path
skillsaw tree /path/to/repo
```

Example output:

```
my-marketplace/
    ├── AGENTS.md (agents-md)
    ├── marketplace.json
    ├── plugins/ [marketplace]
    │   └── my-plugin/ [plugin]
    │       ├── hello.md (command)
    │       └── my-skill/ [skill]
    │           └── SKILL.md (skill)
    └── .coderabbit.yaml
        └── reviews.instructions (coderabbit)
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
