"""
Rules for Z.ai ZCode project configuration and plugin packaging.

ZCode reads ``AGENTS.md`` for instructions and Agent Skills from
``.zcode/skills/`` and ``.agents/skills/``, which skillsaw's universal rules
already cover. The ZCode-specific rules in this package validate:

- The project layer: subagent frontmatter in ``.zcode/agents/*.md``, and the
  hooks and MCP servers in ``.zcode/config.json``.
- Plugin packaging: ``.zcode-plugin/plugin.json`` manifests, the hooks a
  ZCode plugin ships, and the root ``marketplace.json`` catalog of a ZCode
  marketplace.
"""

from .agent_valid import ZCodeAgentValidRule
from .config_valid import ZCodeConfigValidRule
from .hooks_valid import ZCodeHooksValidRule
from .marketplace_json_valid import ZCodeMarketplaceJsonValidRule
from .plugin_json_valid import ZCodePluginJsonValidRule

__all__ = [
    "ZCodeAgentValidRule",
    "ZCodeConfigValidRule",
    "ZCodeHooksValidRule",
    "ZCodeMarketplaceJsonValidRule",
    "ZCodePluginJsonValidRule",
]
