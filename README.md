<table><tr>
<td width="200" valign="top"><img src="https://raw.githubusercontent.com/stbenjam/skillsaw/main/images/logo.png" alt="skillsaw logo" width="200"></td>
<td valign="top">

### skillsaw

**Keep your skills sharp.**

A linter for the files that steer AI coding agents.

</td>
</tr>
<tr>
<td colspan="2">

[![PyPI version](https://badge.fury.io/py/skillsaw.svg)](https://badge.fury.io/py/skillsaw) [![PyPI Downloads](https://img.shields.io/pypi/dm/skillsaw)](https://pypi.org/project/skillsaw/) [![Tests](https://github.com/stbenjam/skillsaw/workflows/Tests/badge.svg)](https://github.com/stbenjam/skillsaw/actions/workflows/test.yml) [![codecov](https://codecov.io/gh/stbenjam/skillsaw/branch/main/graph/badge.svg)](https://codecov.io/gh/stbenjam/skillsaw) [![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

</td>
</tr></table>

Agent instructions behave like code, but most teams still review them like
prose. skillsaw gives them a linter. It finds the structural errors and content
problems that make agents less reliable: vague language, contradictions,
buried priorities, repeated directives, hidden content, broken references,
unsafe configuration, and more.

It understands Agent Skills,
[Agent Plugins v1](https://agent-plugins.org/specification), Claude Code
plugins, OpenAI Codex plugins and marketplaces, CLAUDE.md, AGENTS.md,
GEMINI.md, QWEN.md, Cursor, Copilot, Cline, Devin, Kiro, OpenCode, hooks, agent
configuration, MCP Registry `server.json` publisher metadata, and evals. Safe
structural fixes can be applied automatically; everything else comes with
precise, agent-friendly guidance.

**[Get started](https://skillsaw.org/getting-started/)** |
**[Browse the rules](https://skillsaw.org/rules/)** |
**[Read the documentation](https://skillsaw.org/)**

## See it work

[Watch an AI agent grade, fix, and configure a repository from
scratch.](https://asciinema.org/a/1259880)

[![Watch the skillsaw onboarding demo](https://raw.githubusercontent.com/stbenjam/skillsaw/main/images/onboarding-demo.png)](https://asciinema.org/a/1259880)

## Try it

Paste this into your coding agent to onboard skillsaw now:

```text
Read and follow the instructions at
https://raw.githubusercontent.com/stbenjam/skillsaw/refs/heads/main/skills/skillsaw-onboard/SKILL.md
to onboard this repo to skillsaw.
```

Or run it yourself. No installation is required with
[`uvx`](https://docs.astral.sh/uv/guides/tools/):

```bash
uvx skillsaw tree      # See what skillsaw detects
uvx skillsaw           # Lint the current repository
uvx skillsaw fix       # Apply safe, deterministic fixes
uvx skillsaw baseline  # Accept existing findings and fail only on new ones
```

## What it catches

- **Instruction quality:** weak language, contradictions, tautologies,
  attention dead zones, missing stop conditions, repetitive tool-call
  examples, and bloated context.
- **Structure and compatibility:** invalid frontmatter, manifests, commands,
  skills, agents, hooks, marketplaces, and tool-specific configuration.
- **Security risks:** embedded secrets, invisible Unicode, encoded payloads,
  hidden instructions, unallowlisted dynamic context, dangerous hooks, and
  prohibited MCP servers.
- **Repository drift:** broken references, unreferenced files, inconsistent
  terminology, stale baselines, and context-budget regressions.

The `description-routing` rule checks when-to-use phrasing and descriptions that
only repeat a skill, agent, or command name. Both checks can be configured
independently; see the [rule reference](https://skillsaw.org/rules/description-routing/).

Every rule runs offline. The one exception,
`content-broken-external-reference`, checks whether external `http(s)` links
are still reachable: it is disabled by default, reports only `404` and `410`,
and suits a scheduled job rather than a per-PR gate. Because the linted
repository's own config decides which rules are enabled, the guarantee that
skillsaw stays offline belongs to whoever runs it — `--no-network` (or
`SKILLSAW_NO_NETWORK=1`) refuses network access on `lint`, `fix`, `baseline`,
and `badge` no matter what the repository asks for, and the GitHub Action
sets it by default. See the
[rule reference](https://skillsaw.org/rules/content-broken-external-reference/).

skillsaw detects the repository type automatically and can lint multiple types
in the same project. See [supported repository
types](https://skillsaw.org/repo-types/) and the [complete rule
reference](https://skillsaw.org/rules/) for details.

## Built for real workflows

skillsaw works locally, in CI, and inside coding-agent workflows. It provides
line-level findings, explanations for every rule, deterministic autofixes,
baselines for gradual adoption, GitHub and GitLab integration, and text, JSON,
SARIF, HTML, and Code Climate output. Rules are configurable, and projects can
add local rules or install rule plugins. Typo'd or wrong-typed rule options
in `.skillsaw.yaml` are reported with did-you-mean suggestions instead of
being silently ignored.

| Goal | Documentation |
| --- | --- |
| Install and run skillsaw | [Getting Started](https://skillsaw.org/getting-started/) |
| Tune rules and exclusions | [Configuration](https://skillsaw.org/configuration/) |
| Adopt it without fixing everything at once | [Baselines](https://skillsaw.org/baseline/) |
| Convert plugins to Agent Plugins v1 with `skillsaw port` | [Porting to Agent Plugins](https://skillsaw.org/porting/) |
| Add checks to pull requests | [CI Integration](https://skillsaw.org/ci/) |
| Understand and apply fixes | [Autofixing](https://skillsaw.org/autofixing/) |
| Create project-specific checks | [Custom Rules](https://skillsaw.org/custom-rules/) |
| Publish reusable rule packages | [Rule Plugins](https://skillsaw.org/plugins/) |
| Review the security model | [Supply Chain Protection](https://skillsaw.org/supply-chain-protection/) |
| Look up commands and flags | [CLI Reference](https://skillsaw.org/cli/) |
| Feed the docs to an AI agent | [llms.txt](https://skillsaw.org/llms.txt) index, [llms-full.txt](https://skillsaw.org/llms-full.txt) full docs |

## Measure the result

Every run produces a letter grade based on weighted violation density. The
same data can be rendered as a self-contained report card for a README or
project dashboard.

<a href="https://skillsaw.org/"><img src="https://raw.githubusercontent.com/stbenjam/skillsaw/main/.skillsaw-card.svg" alt="skillsaw report card" width="495"></a>

*skillsaw's own report card, generated with `skillsaw badge --large`.*

Learn how to generate a [grade badge and report
card](https://skillsaw.org/cli/#skillsaw-badge) for your project.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the
project guidelines and [DEVELOPMENT.md](DEVELOPMENT.md) for the local setup.

Questions and bug reports belong in [GitHub
Issues](https://github.com/stbenjam/skillsaw/issues). For a shareable diagnostic
bundle, run `skillsaw feedback` in the affected repository and review the ZIP
before attaching it to an issue — files you add with `--include` are copied in
verbatim. skillsaw is licensed under
the [Apache License 2.0](LICENSE).

## Thank you to our contributors

skillsaw is better because people contribute code, bug reports, and ideas. Thank
you!

<!-- contributors:start -->
<table width="100%">
  <tr>
    <th colspan="4" align="left">Contributors</th>
  </tr>
  <tr>
    <td width="25%"><a href="https://github.com/alSergey"><code>@alSergey</code></a></td>
    <td width="25%"><a href="https://github.com/amy"><code>@amy</code></a></td>
    <td width="25%"><a href="https://github.com/btiernay"><code>@btiernay</code></a></td>
    <td width="25%"><a href="https://github.com/cblecker"><code>@cblecker</code></a></td>
  </tr>
  <tr>
    <td width="25%"><a href="https://github.com/cgwalters"><code>@cgwalters</code></a></td>
    <td width="25%"><a href="https://github.com/ehelms"><code>@ehelms</code></a></td>
    <td width="25%"><a href="https://github.com/EmilienM"><code>@EmilienM</code></a></td>
    <td width="25%"><a href="https://github.com/jeffreylo"><code>@jeffreylo</code></a></td>
  </tr>
  <tr>
    <td width="25%"><a href="https://github.com/jfchevrette"><code>@jfchevrette</code></a></td>
    <td width="25%"><a href="https://github.com/kannon92"><code>@kannon92</code></a></td>
    <td width="25%"><a href="https://github.com/nyechiel"><code>@nyechiel</code></a></td>
    <td width="25%"><a href="https://github.com/rajusem"><code>@rajusem</code></a></td>
  </tr>
  <tr>
    <td width="25%"><a href="https://github.com/skyth3r"><code>@skyth3r</code></a></td>
    <td width="25%"><a href="https://github.com/tchughesiv"><code>@tchughesiv</code></a></td>
    <td width="25%"><a href="https://github.com/tyraziel"><code>@tyraziel</code></a></td>
    <td width="25%"></td>
  </tr>
</table>
<!-- contributors:end -->
