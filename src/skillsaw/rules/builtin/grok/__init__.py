"""
Rules for Grok Build's repository-shipped configuration

Grok Build reads ``AGENTS.md`` for portable instructions and portable Agent
Skills from ``.grok/skills/``, both of which the shared content, security
and skill rules already cover. What is Grok's own and structural is
whatever its loader refuses without a word. In the project layer that is
``.grok/hooks/*.json``, where one wrong-typed field costs the whole file,
and ``.grok/agents/*.md``, where a missing ``name`` or ``description`` costs
the subagent.

Packaging is the other half, and it is silent in the same way. A plugin
manifest that fails to load takes the whole directory with it while ``grok
plugin install`` still prints success; a catalog that fails to parse is
discarded and discovery falls back to scanning ``plugins/``; an entry with a
path that does not resolve is dropped where nothing lists it; and a
``plugin-index.json`` that drifts from its catalog blanks the component
listing the marketplace browser shows.

``.grok/commands/*.md`` has no rule of its own by design — Grok loads a
command with no frontmatter at all, naming it from the filename, so there is
nothing structural to require.
"""

from .agent_valid import GrokAgentValidRule
from .hooks_valid import GrokHooksValidRule
from .marketplace_index_parity import GrokMarketplaceIndexParityRule
from .marketplace_json_valid import GrokMarketplaceJsonValidRule
from .plugin_json_valid import GrokPluginJsonValidRule
from .plugin_structure import GrokPluginStructureRule

__all__ = [
    "GrokAgentValidRule",
    "GrokHooksValidRule",
    "GrokMarketplaceIndexParityRule",
    "GrokMarketplaceJsonValidRule",
    "GrokPluginJsonValidRule",
    "GrokPluginStructureRule",
]
