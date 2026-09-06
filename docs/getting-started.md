# Getting Started

No install required — run with `uvx skillsaw` (or [install](#installation)
it for repeated use).

## Quick Start

```bash
# 1. Lint it
uvx skillsaw

# 2. Fix what you can automatically
uvx skillsaw fix

# 3. Accept remaining violations as the baseline
uvx skillsaw baseline

# Done — only new violations will fail from here on
uvx skillsaw   # exit 0
```

Over time, fix violations and re-run `uvx skillsaw baseline` to shrink the
accepted set. See the [Baseline guide](baseline.md) for details on how
fingerprinting works and configuration options.

## :sparkles: Onboard with AI

!!! tip "Skip the manual setup - paste the below into your tool of choice"

    ```text
    Read and follow the instructions at
    https://raw.githubusercontent.com/stbenjam/skillsaw/refs/heads/main/skills/skillsaw-onboard/SKILL.md
    to onboard this repo to skillsaw.
    ```

Or install the plugin globally for regular use (recommended):

=== "Claude Code"

    ```bash
    claude plugin marketplace add stbenjam/skillsaw
    claude plugin install skillsaw@skillsaw-marketplace
    ```

    Then type **`/skillsaw-onboard`** and follow the prompts.

=== "Codex"

    ```bash
    codex plugin marketplace add stbenjam/skillsaw
    codex plugin add skillsaw@skillsaw-marketplace
    ```

    Start a new Codex session, then invoke **`$skillsaw-onboard`**.

## Keep skillsaw updated

When a new skillsaw release is out, the **`skillsaw-update`** skill walks
your agent through the upgrade: it installs the newest version, reports which
rules are new and what they find in your repository, and bumps pinned
versions in GitHub Actions workflows, Makefile targets, and pre-commit hooks.

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
    docker run --user "$(id -u):$(id -g)" -v "$(pwd):/workspace" ghcr.io/stbenjam/skillsaw
    ```

    The image runs as a non-root user. Mapping your host UID/GID keeps
    `fix`, `badge`, and `baseline` able to write to the bind-mounted checkout.

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
  ✗ ERROR (agentskill-name) [*] [skills/my-skill/SKILL.md:2]: Name 'My Skill' must contain only lowercase letters, numbers, and hyphens
  ✗ ERROR (plugin-json-required) [plugins/git/.claude-plugin/plugin.json]: Missing plugin.json

Warnings:
  ⚠ WARNING (agentskill-description) [skills/helper/SKILL.md:3]: Description exceeds 1024 characters (1087)
  ⚠ WARNING (claude-plugin-readme) [plugins/utils]: Missing README.md (recommended)

Summary:
  Errors:   2
  Warnings: 2
  [*] 1 violation(s) fixable with `skillsaw fix`
```

Violations that `skillsaw fix` can resolve automatically are marked with
`[*]` (safe fixes) or `[?]` (suggested fixes, applied with
`skillsaw fix --suggest`) — see [Autofixing](autofixing.md).

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success (no violations at or above the failure threshold) |
| `1` | Failure (errors found; warnings in strict mode; any violation with `fail-on: info`) |

## More Commands

```bash
# View detected repositories, plugins, skills, and configuration files
skillsaw tree

# Get detailed documentation and configuration options for any rule
skillsaw explain content-weak-language

# Accept existing findings and fail only on new violations
skillsaw baseline

# Generate a grade badge and SVG report card for your README
skillsaw badge --large .

# Generate default config you can customize
skillsaw init

# Verbose output (includes info-level findings)
skillsaw -v

# Strict mode (warnings become errors)
skillsaw --strict

# Output in different formats (text, json, sarif, html, code-climate, gitlab)
skillsaw --format json
skillsaw --format sarif

# Write formatted output directly to a file (format inferred from extension)
skillsaw --output report.sarif
skillsaw --output gitlab:gl-code-quality.json

# Create a diagnostic feedback bundle for bug reports
skillsaw feedback --message "Unexpected finding on custom hook"
```

See the [CLI Reference](cli.md) for all flags and options.


## What's Next?

- Learn about [Repository Types](repo-types.md) that skillsaw detects
- Browse the [Rules Reference](rules/index.md) to see what skillsaw checks
- Set up [Configuration](configuration.md) for your project
- Use a [Baseline](baseline.md) to adopt skillsaw without fixing everything first
- Learn about [Autofixing](autofixing.md) — deterministic fixes and coding agent workflows
