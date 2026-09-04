---
hide:
  - navigation
  - toc
---

<div class="hero" markdown>

<div class="hero-body" markdown>

<div class="hero-copy" markdown>

# Keep your skills sharp.

<p class="hero-subtitle" markdown>
skillsaw lints the files that steer your AI coding agents: skills, plugins,
instructions, and tool configs across Claude Code, Codex, Copilot, Agent Skills,
Google Antigravity, OpenCode, and more. It catches security risks, structural flaws, and content dead
zones with 101 rules, then applies deterministic autofixes.
</p>

<p class="hero-badges" markdown>
[![PyPI version](https://img.shields.io/pypi/v/skillsaw?label=PyPI&color=1f8a56)](https://pypi.org/project/skillsaw/)
[![Tests](https://github.com/stbenjam/skillsaw/workflows/Tests/badge.svg)](https://github.com/stbenjam/skillsaw/actions/workflows/test.yml)
[![License](https://img.shields.io/badge/License-Apache%202.0-24476b.svg)](https://opensource.org/licenses/Apache-2.0)
[![skillsaw grade](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fstbenjam%2Fskillsaw%2Fmain%2F.skillsaw-badge.json)](https://github.com/stbenjam/skillsaw)
</p>

<p class="hero-actions" markdown>
[Get Started](getting-started.md){ .md-button .md-button--primary }
[View Rules](rules/index.md){ .md-button }
</p>

</div>

<div class="hero-features" markdown>

<div class="grid cards" markdown>

-   :shield:{ .lg .middle } **Security & Supply Chain**

    ---

    [Supply chain protection](supply-chain-protection.md) blocks **dangerous lifecycle hooks** (`curl | sh`, `eval`, arbitrary execution),
    prohibited MCP servers, invisible Unicode (ASCII smuggling), high-entropy encoded payloads,
    and unallowlisted dynamic context before they run.

-   :package:{ .lg .middle } **Multi-Ecosystem Structure**

    ---

    Schema and syntax validation across [supported ecosystems](repo-types.md): Agent Skills,
    Claude Code, OpenAI Codex, Grok Build, Google Antigravity, Agent Plugins v1, Copilot custom agents, OpenCode, Muse Code, APM, and MCP Registry.

-   :wrench:{ .lg .middle } **Deterministic Autofixes**

    ---

    Safe, instant [autofixes](autofixing.md) via `skillsaw fix`; bundled skills guide coding
    agents through remaining manual resolutions — see demo below.

-   :brain:{ .lg .middle } **Context & Token Economy**

    ---

    [Research-backed](research.md) content intelligence: eliminates instruction drift,
    attention dead zones, cognitive overload, contradictions, and redundant tooling.

-   :robot:{ .lg .middle } **CI-Ready & Baselines**

    ---

    [GitHub and GitLab integration](ci.md) with PR comments, SARIF reporting, and
    [baselines](baseline.md) for gradual, zero-friction adoption.

-   :electric_plug:{ .lg .middle } **Extensible**

    ---

    [Custom rules](custom-rules.md) in Python, pip-installable [rule plugins](plugins.md),
    and typed [lint tree](lint-tree.md) traversal tailor skillsaw to your repository.

</div>

</div>

</div>


<div class="hero-demo">
<script src="https://asciinema.org/a/1259880.js" id="asciicast-1259880" async data-autoplay="true" data-loop="true" data-speed="1.5" data-theme="dracula"></script>
<noscript><p>▶️ <strong><a href="https://asciinema.org/a/1259880">Watch the onboarding demo</a></strong> — see an AI agent grade, fix, and configure a repo from scratch.</p></noscript>
</div>

<p class="hero-subtitle" markdown>
Reading this with an AI agent? Fetch [llms.txt](https://skillsaw.org/llms.txt)
for an index of the docs, or [llms-full.txt](https://skillsaw.org/llms-full.txt)
for everything in one plain-markdown file.
</p>

</div>
