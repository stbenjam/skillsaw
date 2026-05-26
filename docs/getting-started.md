# Getting Started

## Quick Start

```bash
# Lint current directory (no install required)
uvx skillsaw

# Generate default config you can customize
skillsaw init

# View the lint tree (what skillsaw sees)
skillsaw tree

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

=== "uvx (no install required)"

    ```bash
    uvx skillsaw
    uvx skillsaw /path/to/skills
    ```

=== "pip"

    ```bash
    pip install skillsaw
    ```

=== "From source"

    ```bash
    git clone https://github.com/stbenjam/skillsaw.git
    cd skillsaw
    pip install -e .
    ```

=== "Docker"

    ```bash
    docker pull ghcr.io/stbenjam/skillsaw:latest
    docker run -v $(pwd):/workspace ghcr.io/stbenjam/skillsaw
    ```

=== "GitHub Action"

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

    See the [CI Integration](ci.md) guide for PR review comments and advanced usage.

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

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success (no errors, or warnings only in non-strict mode) |
| `1` | Failure (errors found, or warnings in strict mode) |

## What's Next?

- Learn about [Repository Types](repo-types.md) that skillsaw detects
- Browse the [Rules Reference](rules/index.md) to see what skillsaw checks
- Set up [Configuration](configuration.md) for your project
- Enable [LLM Autofixing](autofixing.md) for content quality
