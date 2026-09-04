"""
Rules for Grok Build repository configuration and packaging.

Grok Build reads ``AGENTS.md`` for portable instructions and loads Agent
Skills from ``.grok/skills/``, both supported by skillsaw's universal rules.
The Grok-specific rules in this package validate:

- Project layer configuration: subagent frontmatter in ``.grok/agents/*.md``,
  project settings in ``.grok/config.toml``, and lifecycle hooks in
  ``.grok/hooks/*.json``.
- Plugin packaging: manifests in ``.grok-plugin/plugin.json`` and marketplace
  catalogs in ``.grok-plugin/marketplace.json`` and ``plugin-index.json``.

These checks ensure your project configuration, subagents, hooks, and
packaged plugins load smoothly across Grok Build environments.
"""

from .agent_valid import GrokAgentValidRule
from .config_project_scope import GrokConfigProjectScopeRule
from .config_valid import GrokConfigValidRule
from .hooks_valid import GrokHooksValidRule
from .marketplace_index_parity import GrokMarketplaceIndexParityRule
from .marketplace_json_valid import GrokMarketplaceJsonValidRule
from .plugin_json_valid import GrokPluginJsonValidRule
from .plugin_structure import GrokPluginStructureRule

__all__ = [
    "GrokAgentValidRule",
    "GrokConfigProjectScopeRule",
    "GrokConfigValidRule",
    "GrokHooksValidRule",
    "GrokMarketplaceIndexParityRule",
    "GrokMarketplaceJsonValidRule",
    "GrokPluginJsonValidRule",
    "GrokPluginStructureRule",
]
