"""The repository type enumeration.

Its own module because the CLI's argument parser needs the vocabulary of
repository types — for ``--type``'s choices and its help text — long
before it needs anything that can read a repository. Reaching for it
through :mod:`skillsaw.context` would pull discovery, the format
packages, and both YAML parsers into an invocation that has not yet
decided whether it is going to lint anything.

:mod:`skillsaw.context` re-exports it, so ``from skillsaw.context import
RepositoryType`` keeps working.
"""

from enum import Enum


class RepositoryType(Enum):
    """Type of repository"""

    SINGLE_PLUGIN = "single-plugin"  # Single plugin at repo root
    MARKETPLACE = "marketplace"  # Marketplace with multiple plugins
    AGENTSKILLS = "agentskills"  # agentskills.io skill repo
    DOT_CLAUDE = "dot-claude"  # .claude/ directory with commands, skills, hooks, etc.
    CODERABBIT = "coderabbit"  # Repository with .coderabbit.yaml
    APM = "apm"  # Repository with .apm/ directory (Agent Package Manager)
    PROMPTFOO = "promptfoo"  # Repository with promptfoo eval configs
    CODEX_PLUGIN = "codex-plugin"  # OpenAI Codex plugin (.codex-plugin/plugin.json)
    CODEX_MARKETPLACE = "codex-marketplace"  # .agents/plugins/marketplace.json
    AGENT_PLUGIN = "agent-plugin"  # Portable Agent Plugins plugin.json
    MCP_REGISTRY = "mcp-registry"  # MCP Registry server.json publisher metadata
    UNKNOWN = "unknown"  # Not a recognized repo type
