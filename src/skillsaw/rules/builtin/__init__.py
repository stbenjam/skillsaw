"""
Builtin linting rules for Claude Code plugins
"""

from .plugin_structure import (
    PluginJsonRequiredRule,
    PluginJsonValidRule,
    PluginNamingRule,
    CommandsDirRequiredRule,
    CommandsExistRule,
    PluginReadmeRule,
)

from .command_format import (
    CommandNamingRule,
    CommandFrontmatterRule,
    CommandSectionsRule,
    CommandNameFormatRule,
)

from .marketplace import (
    MarketplaceJsonValidRule,
    MarketplaceRegistrationRule,
)

from .skills import (
    SkillFrontmatterRule,
)

from .agents import (
    AgentFrontmatterRule,
)

from .hooks import (
    HooksJsonValidRule,
)

from .mcp import (
    McpValidJsonRule,
    McpProhibitedRule,
)

from .agentskills import (
    AgentSkillValidRule,
    AgentSkillNameRule,
    AgentSkillDescriptionRule,
    AgentSkillStructureRule,
    AgentSkillEvalsRequiredRule,
    AgentSkillEvalsRule,
)

# All builtin rules
BUILTIN_RULES = [
    # Plugin structure
    PluginJsonRequiredRule,
    PluginJsonValidRule,
    PluginNamingRule,
    CommandsDirRequiredRule,
    CommandsExistRule,
    PluginReadmeRule,
    # Command format
    CommandNamingRule,
    CommandFrontmatterRule,
    CommandSectionsRule,
    CommandNameFormatRule,
    # Marketplace
    MarketplaceJsonValidRule,
    MarketplaceRegistrationRule,
    # Skills
    SkillFrontmatterRule,
    # Agents
    AgentFrontmatterRule,
    # Hooks
    HooksJsonValidRule,
    # MCP
    McpValidJsonRule,
    McpProhibitedRule,
    # Agentskills
    AgentSkillValidRule,
    AgentSkillNameRule,
    AgentSkillDescriptionRule,
    AgentSkillStructureRule,
    AgentSkillEvalsRequiredRule,
    AgentSkillEvalsRule,
]


__all__ = [
    "BUILTIN_RULES",
    # Export individual rules too
    "PluginJsonRequiredRule",
    "PluginJsonValidRule",
    "PluginNamingRule",
    "CommandsDirRequiredRule",
    "CommandsExistRule",
    "PluginReadmeRule",
    "CommandNamingRule",
    "CommandFrontmatterRule",
    "CommandSectionsRule",
    "CommandNameFormatRule",
    "MarketplaceJsonValidRule",
    "MarketplaceRegistrationRule",
    "SkillFrontmatterRule",
    "AgentFrontmatterRule",
    "HooksJsonValidRule",
    "McpValidJsonRule",
    "McpProhibitedRule",
    "AgentSkillValidRule",
    "AgentSkillNameRule",
    "AgentSkillDescriptionRule",
    "AgentSkillStructureRule",
    "AgentSkillEvalsRequiredRule",
    "AgentSkillEvalsRule",
]
