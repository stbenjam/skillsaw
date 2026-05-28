# Getting Started

No install required — run with `uvx skillsaw` (or [install](#installation)
it for repeated use).

## Quick Start

```bash
# 1. See what skillsaw detects in your repo
skillsaw tree

# 2. Lint it
skillsaw

# 3. Fix what you can automatically
skillsaw fix

# 4. Accept remaining violations as the baseline
skillsaw baseline

# Done — only new violations will fail from here on
skillsaw   # exit 0
```

## More Commands

```bash
# Fix content quality issues with an LLM (requires extras)
# pip install skillsaw[llm]       — or: skillsaw[vertexai], skillsaw[bedrock]
# uvx --from "skillsaw[llm]" skillsaw fix --llm
skillsaw fix --llm

# Generate default config you can customize
skillsaw init

# Verbose output (includes info-level findings)
skillsaw -v

# Strict mode (warnings become errors)
skillsaw --strict

# List all rules with fix support info
skillsaw list-rules

# Generate plugin/skill documentation
skillsaw docs

# Output in different formats (text, json, sarif, html, code-climate)
skillsaw --format json
skillsaw --format code-climate   # Code Climate / GitLab Code Quality format
skillsaw --format gitlab          # Alias for code-climate

# Write formatted output to a file (format inferred from extension)
skillsaw --output report.sarif

# Explicit format prefix (needed when extension is ambiguous, e.g. .json)
skillsaw --output gitlab:gl-code-quality.json
skillsaw --output json:native-report.json

# Multiple outputs in one run
skillsaw --output report.sarif --output gitlab:gl-code-quality.json

# Scaffold a new marketplace, plugin, or skill
skillsaw add marketplace
skillsaw add plugin my-plugin
skillsaw add skill my-skill
```

See the [CLI Reference](cli.md) for all flags and options.

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

## Adopting on an Existing Project

Most projects will have violations when first running skillsaw. You have
three options — fix them, disable noisy rules for your use case, or
use a **baseline** to get passing immediately:

```bash
# 1. Set up config
skillsaw init

# 2. Accept current violations
skillsaw baseline

# 3. CI passes — only new violations will fail
skillsaw lint  # exit 0
```

Over time, fix violations and re-run `skillsaw baseline` to shrink the
accepted set. See the [Baseline guide](baseline.md) for details on how
fingerprinting works and configuration options.

## What's Next?

- Learn about [Repository Types](repo-types.md) that skillsaw detects
- Browse the [Rules Reference](rules/index.md) to see what skillsaw checks
- Set up [Configuration](configuration.md) for your project
- Use a [Baseline](baseline.md) to adopt skillsaw without fixing everything first
- Enable [LLM Autofixing](autofixing.md) for content quality
