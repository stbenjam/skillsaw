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

Over time, fix violations and re-run `skillsaw baseline` to shrink the
accepted set. See the [Baseline guide](baseline.md) for details on how
fingerprinting works and configuration options.

## :sparkles: Onboard with AI

!!! tip "Skip the manual setup — let your AI coding agent do it all"

    The **`/skillsaw-onboard`** skill walks your agent through the full
    adoption flow in one interactive session:

    | | Step | What happens |
    |---|---|---|
    | :material-numeric-1-circle:{ .step-icon } | **Install** | Adds skillsaw to your project |
    | :material-numeric-2-circle:{ .step-icon } | **Lint** | Runs a full scan of your repo |
    | :material-numeric-3-circle:{ .step-icon } | **Autofix** | Applies deterministic fixes automatically |
    | :material-numeric-4-circle:{ .step-icon } | **Manual fix** | Your agent resolves remaining violations interactively |
    | :material-numeric-5-circle:{ .step-icon } | **CI** | Sets up CI to lint on every PR |
    | :material-numeric-6-circle:{ .step-icon } | **Baseline** | Accepts any leftover violations so you start clean |

=== "Claude Code"

    ```bash
    claude plugin marketplace add stbenjam/skillsaw
    claude plugin install skillsaw@skillsaw-marketplace
    ```

    Then type **`/skillsaw-onboard`** and follow the prompts.

=== "Other AI coding agents"

    Paste this into your coding agent:

    ```
    Read and follow the instructions at
    https://raw.githubusercontent.com/stbenjam/skillsaw/refs/heads/main/skills/skillsaw-onboard/SKILL.md
    to onboard this repo to skillsaw.
    ```

    Or consult your agent's documentation for how to install a new
    [agentskills.io](https://agentskills.io) skill.

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
  ✗ ERROR (agentskill-name) [*] [skills/my-skill/SKILL.md:2]: Name 'My Skill' must contain only lowercase letters, numbers, and hyphens
  ✗ ERROR (plugin-json-required) [plugins/git/.claude-plugin/plugin.json]: Missing plugin.json

Warnings:
  ⚠ WARNING (agentskill-description) [skills/helper/SKILL.md:3]: Description exceeds 1024 characters (1087)
  ⚠ WARNING (plugin-readme) [plugins/utils]: Missing README.md (recommended)

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
# Your coding agent can fix content violations directly — just run
# skillsaw and let the agent read the output. For detailed guidance:
skillsaw explain content-weak-language

# Generate default config you can customize
skillsaw init

# Verbose output (includes info-level findings)
skillsaw -v

# Strict mode (warnings become errors)
skillsaw --strict

# Fail on any violation, even info-level (see Configuration → Failure Threshold)
skillsaw --fail-on info

# List all rules with fix support info
skillsaw list-rules

# Generate plugin/skill documentation
skillsaw docs

# Output in different formats (text, json, sarif, html, code-climate, gitlab)
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

## What's Next?

- Learn about [Repository Types](repo-types.md) that skillsaw detects
- Browse the [Rules Reference](rules/index.md) to see what skillsaw checks
- Set up [Configuration](configuration.md) for your project
- Use a [Baseline](baseline.md) to adopt skillsaw without fixing everything first
- Learn about [Autofixing](autofixing.md) — deterministic fixes and coding agent workflows
