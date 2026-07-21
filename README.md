<table><tr>
<td width="200" valign="top"><img src="https://raw.githubusercontent.com/stbenjam/skillsaw/main/images/logo.png" alt="skillsaw logo" width="200"></td>
<td valign="top">

### skillsaw

**Keep your skills sharp.**

A linter for the files that steer AI coding agents.

[![PyPI version](https://badge.fury.io/py/skillsaw.svg)](https://badge.fury.io/py/skillsaw) [![Tests](https://github.com/stbenjam/skillsaw/workflows/Tests/badge.svg)](https://github.com/stbenjam/skillsaw/actions/workflows/test.yml) [![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

</td>
</tr></table>

Agent instructions behave like code, but most teams still review them like
prose. skillsaw gives them a linter. It finds the structural errors and content
problems that make agents less reliable: vague language, contradictions,
buried priorities, repeated directives, hidden content, broken references,
unsafe configuration, and more.

It understands Agent Skills, Claude Code plugins, CLAUDE.md, AGENTS.md,
GEMINI.md, Cursor, Copilot, Kiro, hooks, agent configuration, and evals. Safe
structural fixes can be applied automatically; everything else comes with
precise, agent-friendly guidance.

**[Get started](https://skillsaw.org/getting-started/)** |
**[Browse the rules](https://skillsaw.org/rules/)** |
**[Read the documentation](https://skillsaw.org/)**

## See it work

[![Watch the skillsaw onboarding demo](https://raw.githubusercontent.com/stbenjam/skillsaw/main/images/onboarding-demo.png)](https://asciinema.org/a/1259880)

[Watch an AI agent grade, fix, and configure a repository from
scratch.](https://asciinema.org/a/1259880)

## Try it

No installation is required with [`uvx`](https://docs.astral.sh/uv/guides/tools/):

```bash
uvx skillsaw tree      # See what skillsaw detects
uvx skillsaw           # Lint the current repository
uvx skillsaw fix       # Apply safe, deterministic fixes
uvx skillsaw baseline  # Accept existing findings and fail only on new ones
```

Prefer to let your coding agent handle setup, fixes, CI, and the initial
baseline? Follow the [AI onboarding
guide](https://skillsaw.org/getting-started/#onboard-with-ai).

## What it catches

- **Instruction quality:** weak language, contradictions, tautologies,
  attention dead zones, missing stop conditions, and bloated context.
- **Structure and compatibility:** invalid frontmatter, manifests, commands,
  skills, agents, hooks, marketplaces, and tool-specific configuration.
- **Security risks:** embedded secrets, invisible Unicode, encoded payloads,
  hidden instructions, dangerous hooks, and prohibited MCP servers.
- **Repository drift:** broken references, unreferenced files, inconsistent
  terminology, stale baselines, and context-budget regressions.

skillsaw detects the repository type automatically and can lint multiple types
in the same project. See [supported repository
types](https://skillsaw.org/repo-types/) and the [complete rule
reference](https://skillsaw.org/rules/) for details.

## Built for real workflows

skillsaw works locally, in CI, and inside coding-agent workflows. It provides
line-level findings, explanations for every rule, deterministic autofixes,
baselines for gradual adoption, GitHub and GitLab integration, and text, JSON,
SARIF, HTML, and Code Climate output. Rules are configurable, and projects can
add local rules or install rule plugins.

| Goal | Documentation |
| --- | --- |
| Install and run skillsaw | [Getting Started](https://skillsaw.org/getting-started/) |
| Tune rules and exclusions | [Configuration](https://skillsaw.org/configuration/) |
| Adopt it without fixing everything at once | [Baselines](https://skillsaw.org/baseline/) |
| Add checks to pull requests | [CI Integration](https://skillsaw.org/ci/) |
| Understand and apply fixes | [Autofixing](https://skillsaw.org/autofixing/) |
| Create project-specific checks | [Custom Rules](https://skillsaw.org/custom-rules/) |
| Publish reusable rule packages | [Rule Plugins](https://skillsaw.org/plugins/) |
| Review the security model | [Supply Chain Protection](https://skillsaw.org/supply-chain-protection/) |
| Look up commands and flags | [CLI Reference](https://skillsaw.org/cli/) |

## Measure the result

Every run produces a letter grade based on weighted violation density. The
same data can be rendered as a self-contained report card for a README or
project dashboard.

<a href="https://skillsaw.org/"><img src="https://raw.githubusercontent.com/stbenjam/skillsaw/main/.skillsaw-card.svg" alt="skillsaw report card" width="495"></a>

*skillsaw's own report card, generated with `skillsaw badge --large`.*

Learn how to generate the [grade badge and report
card](https://skillsaw.org/cli/#skillsaw-badge).

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the
project guidelines and [DEVELOPMENT.md](DEVELOPMENT.md) for the local setup.

Questions and bug reports belong in [GitHub
Issues](https://github.com/stbenjam/skillsaw/issues). skillsaw is licensed under
the [Apache License 2.0](LICENSE).
