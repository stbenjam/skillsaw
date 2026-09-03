"""The repository type vocabulary.

What a repository *is* — how it packages its content and which tools it is
configured for — named in one place. ``skillsaw.context`` composes the
verdict over these; discovery works in the string values so it can stay
free of any import from the context layer.
"""

from __future__ import annotations

from enum import Enum


class RepositoryType(Enum):
    """Type of repository.

    One set covers both halves of "what is this repository": how its content
    is packaged (a marketplace, a plugin, an APM project) and which tools it
    is configured for (Cursor, Codex, Muse Code). If a repository holds a
    tool's configuration, the summary says so and that tool's rules run —
    the two concepts were once split across repository types and format
    labels, which left a repository whose only agent content was
    ``.muse/hooks.json`` reporting ``unknown``.
    """

    SINGLE_PLUGIN = "single-plugin"  # Single plugin at repo root
    MARKETPLACE = "marketplace"  # Marketplace with multiple plugins
    AGENTSKILLS = "agentskills"  # agentskills.io skill repo
    DOT_CLAUDE = "dot-claude"  # .claude/ directory with commands, skills, hooks, etc.
    CODERABBIT = "coderabbit"  # Repository with .coderabbit.yaml
    APM = "apm"  # Repository with .apm/ directory (Agent Package Manager)
    PROMPTFOO = "promptfoo"  # Repository with promptfoo eval configs
    CODEX_PLUGIN = "codex-plugin"  # OpenAI Codex plugin (.codex-plugin/plugin.json)
    CODEX_MARKETPLACE = "codex-marketplace"  # .agents/plugins/marketplace.json
    # Repository with `.codex/` project-layer configuration such as
    # `.codex/hooks.json`; distinct from a Codex plugin or marketplace.
    CODEX_PROJECT = "codex-project"
    AGENT_PLUGIN = "agent-plugin"  # Portable Agent Plugins plugin.json
    MCP_REGISTRY = "mcp-registry"  # MCP Registry server.json publisher metadata
    CURSOR = "cursor"  # Repository with `.cursor/` content or a `.cursorrules`
    COPILOT = "copilot"  # Repository with Copilot / VS Code content under `.github/`
    CLINE = "cline"  # Repository with `.clinerules`
    DEVIN = "devin"  # Repository with `.devin/`, `.windsurf/` or Devin instructions
    OPENCODE = "opencode"  # Repository with an `opencode.json` or `.opencode/`
    MUSE = "muse"  # Repository with `.muse/` configuration — Muse Code
    # Repository with a `.grok/` project layer — skills, rules, commands,
    # agents, hooks, MCP. Grok plugins and marketplaces are separate
    # packaging concerns and are not this type.
    GROK_PROJECT = "grok-project"
    GROK_PLUGIN = "grok-plugin"  # Grok Build plugin (.grok-plugin/plugin.json)
    GROK_MARKETPLACE = "grok-marketplace"  # .grok-plugin/marketplace.json
    KIRO = "kiro"  # Repository with `.kiro/` steering files
    GEMINI = "gemini"  # Repository with a GEMINI.md
    QWEN = "qwen"  # Repository with a QWEN.md
    AGENTS_MD = "agents-md"  # Repository with an AGENTS.md
    CLAUDE_MD = "claude-md"  # Repository with a CLAUDE.md
    SKILLS_LOCK = "skills-lock"  # Repository with a Vercel skills CLI skills-lock.json
    # Antigravity primitives (plugin with plugin.json, or project configuration)
    ANTIGRAVITY_PLUGIN = "antigravity-plugin"
    ANTIGRAVITY = "antigravity"
    UNKNOWN = "unknown"  # Not a recognized repo type


TYPE_PRIORITY: list[RepositoryType] = [
    RepositoryType.MARKETPLACE,
    RepositoryType.SINGLE_PLUGIN,
    RepositoryType.APM,
    RepositoryType.DOT_CLAUDE,
    # Below the Claude equivalents, so a repository that is both keeps
    # its Claude primary type — but above the generic fallbacks: an
    # authored Codex plugin whose skills also match the Agent Skills
    # convention is a Codex plugin first, not an agentskills.io repo.
    RepositoryType.CODEX_MARKETPLACE,
    RepositoryType.CODEX_PLUGIN,
    RepositoryType.GROK_MARKETPLACE,
    RepositoryType.GROK_PLUGIN,
    RepositoryType.ANTIGRAVITY_PLUGIN,
    RepositoryType.AGENT_PLUGIN,
    RepositoryType.AGENTSKILLS,
    RepositoryType.MCP_REGISTRY,
    RepositoryType.CODERABBIT,
    RepositoryType.PROMPTFOO,
    # Tool configuration sorts below everything that describes how the
    # repository packages its content, so a marketplace that also ships
    # a `.cursor/` keeps `marketplace` as its primary type.
    RepositoryType.CODEX_PROJECT,
    RepositoryType.MUSE,
    RepositoryType.GROK_PROJECT,
    RepositoryType.CURSOR,
    RepositoryType.COPILOT,
    RepositoryType.CLINE,
    RepositoryType.DEVIN,
    RepositoryType.OPENCODE,
    RepositoryType.ANTIGRAVITY,
    RepositoryType.KIRO,
    RepositoryType.SKILLS_LOCK,
    RepositoryType.CLAUDE_MD,
    RepositoryType.AGENTS_MD,
    RepositoryType.GEMINI,
    RepositoryType.QWEN,
]


# Repository types whose lint tree can hold Agent Skills. One shared set so a
# newly supported host cannot be wired into some skill rules and forgotten in
# the rest. The Codex types belong here because Codex plugins ship
# ``skills/<name>/SKILL.md`` in the same format, and a catalog repository's
# plugin skills are discovered whether or not CODEX_PLUGIN was also inferred.
# CODEX_PROJECT does not: ``.codex/`` is the project configuration layer, and
# the skills Codex loads live in a plugin. The Grok plugin types are here for
# the same reason as the Codex ones; GROK_PROJECT is not, because ``.grok/``
# earns its skills through ``CONVENTIONAL_SKILL_DIRS`` instead.
SKILL_REPO_TYPES = {
    RepositoryType.AGENTSKILLS,
    RepositoryType.SINGLE_PLUGIN,
    RepositoryType.MARKETPLACE,
    RepositoryType.DOT_CLAUDE,
    RepositoryType.CODEX_PLUGIN,
    RepositoryType.CODEX_MARKETPLACE,
    RepositoryType.AGENT_PLUGIN,
    RepositoryType.GROK_PLUGIN,
    RepositoryType.GROK_MARKETPLACE,
    RepositoryType.ANTIGRAVITY_PLUGIN,
}


#: Types detected from committed tool configuration rather than from how the
#: repository packages its content. Detection reads the shared walk, so
#: ``apply_excludes()`` recomputes exactly these when a caller adds patterns
#: after construction.
TOOL_REPO_TYPES = frozenset(
    {
        RepositoryType.CURSOR,
        RepositoryType.COPILOT,
        RepositoryType.CLINE,
        RepositoryType.DEVIN,
        RepositoryType.OPENCODE,
        RepositoryType.MUSE,
        RepositoryType.GROK_PROJECT,
        RepositoryType.CODEX_PROJECT,
        RepositoryType.ANTIGRAVITY,
        RepositoryType.KIRO,
        RepositoryType.GEMINI,
        RepositoryType.QWEN,
        RepositoryType.AGENTS_MD,
        RepositoryType.CLAUDE_MD,
        RepositoryType.CODERABBIT,
        RepositoryType.SKILLS_LOCK,
    }
)


# Repository types that may hold one of ``INSTRUCTION_FILES``. CLINE,
# OPENCODE, MUSE, GROK_PROJECT and CODEX_PROJECT are deliberately absent:
# the instruction-file rules only ever look at
# AGENTS.md/CLAUDE.md/GEMINI.md/QWEN.md, so a repository whose only marker is
# ``.clinerules``, ``opencode.json``, ``.muse/hooks.json``, ``.grok/`` or
# ``.codex/hooks.json`` would auto-enable two rules structurally incapable of
# finding anything. OpenCode, Muse Code, Grok Build and Codex do read
# AGENTS.md — and when one is present AGENTS_MD enables them for it. Grok's
# own always-on prose lives in ``.grok/rules/``, which the content rules
# read as content rather than as an instruction file.
INSTRUCTION_REPO_TYPES = frozenset(
    {
        RepositoryType.CURSOR,
        RepositoryType.COPILOT,
        RepositoryType.DEVIN,
        RepositoryType.GEMINI,
        RepositoryType.QWEN,
        RepositoryType.AGENTS_MD,
        RepositoryType.ANTIGRAVITY,
        RepositoryType.KIRO,
        RepositoryType.CLAUDE_MD,
        RepositoryType.CODERABBIT,
    }
)
