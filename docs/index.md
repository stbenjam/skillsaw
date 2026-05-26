---

<div style="text-align: center; padding: 2rem 0;" markdown>

![skillsaw logo](images/logo.png){ width="200" }

**Keep your skills sharp.**

A linter with built-in content intelligence for [agentskills.io](https://agentskills.io) skills,
[Claude Code](https://docs.claude.com/en/docs/claude-code) [plugins](https://docs.claude.com/en/docs/claude-code/plugins),
and [plugin marketplaces](https://docs.claude.com/en/docs/claude-code/plugin-marketplaces).

Analyzes instruction file quality using attention research, detects weak language and contradictions,
and auto-fixes violations with any LLM.

[Get Started](getting-started.md){ .md-button .md-button--primary }
[View Rules](rules/index.md){ .md-button }

</div>

---

## Features

<div class="grid cards" markdown>

-   :brain:{ .lg .middle } **Content Intelligence**

    ---

    [Research-backed](research.md) rules that catch weak language, tautological instructions,
    attention dead zones, embedded secrets, contradictions, and more.

-   :wrench:{ .lg .middle } **LLM Autofix**

    ---

    Fix violations with any LLM via `skillsaw fix --llm` — parallel processing, scoped re-lint,
    per-file rollback.

-   :mag:{ .lg .middle } **Context-Aware**

    ---

    Auto-detects repo type and instruction formats: CLAUDE.md, AGENTS.md, Cursor, Copilot,
    Gemini, Kiro, and more.

-   :triangular_ruler:{ .lg .middle } **50 Rules**

    ---

    Validates structure, metadata, commands, cross-file consistency, context budget, and
    content quality.

-   :building_construction:{ .lg .middle } **Scaffolding**

    ---

    `skillsaw add` generates plugins, skills, commands, agents, and hooks with best-practice
    structure.

-   :memo:{ .lg .middle } **Documentation**

    ---

    `skillsaw docs` generates HTML or Markdown documentation for your plugins and marketplaces.

-   :electric_plug:{ .lg .middle } **Extensible**

    ---

    Custom rules, banned patterns, per-rule thresholds — tailor skillsaw to your project.

-   :robot:{ .lg .middle } **CI-Ready**

    ---

    GitHub Action with inline PR comments, deduplication, and automatic thread resolution.

-   :zap:{ .lg .middle } **Version-Gated**

    ---

    New rules gated behind config versions — no surprises on upgrade.

</div>

---

## Quick Start

```bash
# Lint current directory (no install required)
uvx skillsaw

# Fix structural issues automatically
skillsaw fix

# Fix content quality issues with an LLM
skillsaw fix --llm
```

[:octicons-arrow-right-24: Full installation guide](getting-started.md)
