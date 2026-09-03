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
prose. skillsaw gives them a linter. It validates structure across every major
AI coding ecosytem, guards against many supply-chain attacks, and applies content
and context rules backed by research and frontier lab guidance.

It understands Agent Skills,
[Agent Plugins v1](https://agent-plugins.org/specification), Claude Code
plugins, OpenAI Codex plugins and marketplaces, CLAUDE.md, AGENTS.md,
GEMINI.md, QWEN.md, Cursor, Copilot, Cline, Devin, Kiro, OpenCode, Muse Code,
hooks, agent configuration, MCP Registry `server.json` publisher metadata,
Vercel skills CLI lockfiles, and eval formats. Safe structural fixes can be applied
automatically; everything else comes with precise, agent-friendly guidance.

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

- **Multi-ecosystem structure & compatibility:** schema, frontmatter, and manifest validation for Agent Skills (`SKILL.md`), Claude Code, OpenAI Codex (plugins & marketplaces), Agent Plugins v1 (`plugin.json`, `mcp.json`), GitHub Copilot & VS Code custom agents (`.github/agents/`), OpenCode configuration, APM packages, MCP server maps, and MCP Registry metadata.
- **Content quality & token economy:** research-backed rules detecting instruction drift across duplicate files, lost-in-the-middle attention dead zones, cognitive overload, section length violations, weak language, contradictions, and repetitive inline tool-call examples.
- **Discovery & repository integrity:** unreferenced bundled files, broken internal file references, inconsistent terminology, missing stop conditions, and stale baselines.
- **Security & supply chain:**
  - **Dangerous lifecycle hooks:** blocks arbitrary remote code execution, download-and-execute (`curl | sh`, `wget | bash`), and script obfuscation (`eval`) in `hooks.json` and settings.
  - **Prohibited & unvetted MCP servers:** enforces strict MCP allowlists across root, plugin, and custom agent configurations.
  - **Prompt injection & stealth payloads:** detects invisible Unicode (ASCII smuggling, zero-width tags, bidi overrides), high-entropy encoded payloads (base64/hex), and hidden instructions in comments and code fences.
  - **Environment & context security:** flags dangerous environment overrides (`LD_PRELOAD`, `NODE_OPTIONS`, `PYTHONPATH`), unallowlisted dynamic context injection, and embedded credentials.
 **Deterministic autofixes:** safe, instant automated fixes for invalid frontmatter, broken headings, missing manifests, unclosed code fences, and schema keys via `skillsaw fix`.
skillsaw detects repository types automatically and lints multiple formats in the same project. See [supported repository types](https://skillsaw.org/repo-types/) and the [complete rule reference](https://skillsaw.org/rules/) for details.



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
| Review the security model | [Supply Chain Protection](https://skillsaw.org/supply-chain-protection/) |
| Supported ecosystems and tools | [Repository Types](https://skillsaw.org/repo-types/) |
| Add checks to pull requests & CI | [CI Integration](https://skillsaw.org/ci/) |
| Understand and apply fixes | [Autofixing](https://skillsaw.org/autofixing/) |
| Convert plugins to Agent Plugins v1 | [Porting to Agent Plugins](https://skillsaw.org/porting/) |
| Create project-specific checks | [Custom Rules](https://skillsaw.org/custom-rules/) |
| Publish reusable rule packages | [Rule Plugins](https://skillsaw.org/plugins/) |
| Inspect the typed parse tree | [Lint Tree](https://skillsaw.org/lint-tree/) |
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
