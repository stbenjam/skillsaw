<table><tr>
<td width="200" valign="top"><img src="https://raw.githubusercontent.com/stbenjam/skillsaw/main/images/logo.png" alt="skillsaw logo" width="200"></td>
<td valign="top">

### skillsaw

Keep your skills sharp. skillsaw lints the files that steer AI coding agents:
skills, plugins, CLAUDE.md, AGENTS.md, Cursor/Copilot/Gemini/Kiro context,
CodeRabbit config, Promptfoo evals, and related agent tooling.

[![PyPI version](https://badge.fury.io/py/skillsaw.svg)](https://badge.fury.io/py/skillsaw) [![PyPI Downloads](https://img.shields.io/pypi/dm/skillsaw)](https://pypi.org/project/skillsaw/) [![Tests](https://github.com/stbenjam/skillsaw/workflows/Tests/badge.svg)](https://github.com/stbenjam/skillsaw/actions/workflows/test.yml) [![codecov](https://codecov.io/gh/stbenjam/skillsaw/branch/main/graph/badge.svg)](https://codecov.io/gh/stbenjam/skillsaw) [![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0) [![skillsaw grade](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstbenjam%2Fskillsaw%2Fmain%2F.skillsaw-badge.json)](https://skillsaw.org/)

</td>
</tr></table>

[Full documentation](https://skillsaw.org) | [Getting started](https://skillsaw.org/getting-started/) | [Rules](https://skillsaw.org/rules/) | [Configuration](https://skillsaw.org/configuration/) | [CI](https://skillsaw.org/ci/)

[![Watch the skillsaw onboarding demo](https://raw.githubusercontent.com/stbenjam/skillsaw/main/images/onboarding-demo.png)](https://asciinema.org/a/1259880)

## What It Does

skillsaw is a configurable, rule-based linter for agentic context:

- **Structure**: validates agentskills.io skills, Claude Code plugins and marketplaces, commands, hooks, MCP config, settings files, Promptfoo evals, CodeRabbit config, and more.
- **Content quality**: catches weak language, contradictions, tautologies, attention dead zones, oversized sections, embedded secrets, and instructions that are hard for agents to act on.
- **Adoption flow**: supports deterministic autofixes, baselines for existing issues, CI output formats, and an optional AI-assisted onboarding skill.
- **Extensibility**: supports custom rules and pip-installable rule plugins when the built-in checks are not enough.

The goal is not to lint application source code. It is to keep the instruction
and configuration layer around AI coding agents clear, safe, structured, and
maintainable.

## Quick Start

No install is required if you use `uvx`:

```bash
uvx skillsaw
```

For repeated use:

```bash
pip install skillsaw
skillsaw
```

Common first commands:

```bash
# Show what skillsaw detects in this repository
skillsaw tree

# Lint the current directory
skillsaw

# Apply deterministic autofixes
skillsaw fix

# Accept remaining current issues so only new violations fail
skillsaw baseline

# Explain why a rule fired and how to fix it
skillsaw explain content-weak-language
```

See the [CLI reference](https://skillsaw.org/cli/) for every command, flag,
output format, and exit code.

## Onboard With An Agent

If you want an AI coding agent to do the setup work, install the skillsaw
Claude Code plugin:

```bash
claude plugin marketplace add stbenjam/skillsaw
claude plugin install skillsaw@skillsaw-marketplace
```

Then run:

```text
/skillsaw-onboard
```

That onboarding skill installs skillsaw, scans the repository, applies safe
autofixes, helps resolve remaining findings, sets up CI, and creates a
baseline. Other agents can follow the same workflow from the
[Getting Started guide](https://skillsaw.org/getting-started/#onboard-with-ai).

## What It Checks

skillsaw auto-detects repository types and enables relevant rules. A repository
can match multiple types at once.

Supported areas include:

- [agentskills.io skills](https://skillsaw.org/rules/agentskills/)
- [Claude Code plugins and marketplaces](https://skillsaw.org/plugins/)
- Commands, agents, hooks, settings, and MCP configuration
- CLAUDE.md, AGENTS.md, and other agent-facing instruction files
- [Promptfoo evals](https://skillsaw.org/rules/promptfoo/)
- [CodeRabbit configuration](https://skillsaw.org/rules/coderabbit/)
- [APM packages](https://skillsaw.org/rules/apm/)
- General content quality rules for prose that enters an agent context window

Browse the [rules reference](https://skillsaw.org/rules/) for the full list.

## Adopt It Safely

Most existing repositories have some findings on the first run. The intended
adoption path is:

1. Run `skillsaw` and review the findings.
2. Run `skillsaw fix` for deterministic autofixes.
3. Fix high-value issues manually.
4. Run `skillsaw baseline` to accept anything you are not ready to address.
5. Add CI so new violations fail pull requests.

The baseline file lets teams adopt skillsaw without fixing every historical
issue immediately. Over time, fix old entries and regenerate the baseline.

Read more:

- [Baseline guide](https://skillsaw.org/baseline/)
- [Autofixing guide](https://skillsaw.org/autofixing/)
- [CI integration](https://skillsaw.org/ci/)
- [Pre-commit hook](https://skillsaw.org/pre-commit/)

## Minimal CI

GitHub Actions:

```yaml
name: skillsaw

on: [pull_request]

permissions:
  contents: read

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: stbenjam/skillsaw@v0
        with:
          strict: true
```

For PR comments, SARIF, GitLab Code Quality, custom rules, plugins, and supply
chain guidance, see [CI integration](https://skillsaw.org/ci/) and
[supply chain protection](https://skillsaw.org/supply-chain-protection/).

## Configure

Generate a starter config:

```bash
skillsaw init
```

Typical configuration controls include enabled rules, severity, failure
thresholds, exclude patterns, per-rule excludes, repo type detection, and
content paths. See the [configuration guide](https://skillsaw.org/configuration/)
for the schema and examples.

## Extend

skillsaw can be extended in two ways:

- **Custom rules** live in a repository and run only when custom rules are
  explicitly allowed.
- **Rule plugins** are pip-installable Python packages for sharing rule sets
  across repositories.

Start with [custom rules](https://skillsaw.org/custom-rules/) for local checks
and [rule plugins](https://skillsaw.org/plugins/#rule-plugins) for reusable
distribution.

## Development

```bash
git clone https://github.com/stbenjam/skillsaw.git
cd skillsaw
pip install -e .
make test
make lint
```

Development docs live in [DEVELOPMENT.md](DEVELOPMENT.md). Contributions are
welcome; please include tests for behavior changes and update docs when user
visible behavior changes.

## License

Apache License 2.0. See [LICENSE](LICENSE).
