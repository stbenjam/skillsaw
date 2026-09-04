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
    | :material-numeric-3-circle:{ .step-icon } | **Triage** | Groups findings by rule to plan fixes, baselines, or configuration |
    | :material-numeric-4-circle:{ .step-icon } | **Autofix** | Applies safe, automatic fixes |
    | :material-numeric-5-circle:{ .step-icon } | **Manual fix** | Resolves remaining violations interactively |
    | :material-numeric-6-circle:{ .step-icon } | **CI** | Sets up CI to lint on every PR |
    | :material-numeric-7-circle:{ .step-icon } | **Baseline** | Accepts any leftover violations so you start clean |

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

=== "Other AI coding agents"

    Paste this into your coding agent:

    ```
    Read and follow the instructions at
    https://raw.githubusercontent.com/stbenjam/skillsaw/refs/heads/main/skills/skillsaw-onboard/SKILL.md
    to onboard this repo to skillsaw.
    ```

    Or consult your agent's documentation for how to install a new
    [agentskills.io](https://agentskills.io) skill.

## Keep skillsaw updated

When a new skillsaw release is out, the **`/skillsaw-update`** skill walks
your agent through the upgrade: it installs the newest version, reports which
rules are new and what they find in your repository, and bumps pinned
versions in GitHub Actions workflows and action inputs, Makefile targets,
pre-commit hooks, container image tags in Dockerfiles or GitLab CI, and PyPI
pins.

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
