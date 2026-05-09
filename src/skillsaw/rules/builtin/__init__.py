"""
Builtin linting rules for Claude Code plugins
"""

from .plugin_structure import (
    PluginJsonRequiredRule,
    PluginJsonValidRule,
    PluginNamingRule,
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

from .rules_dir import (
    RulesValidRule,
)

from .agentskills import (
    AgentSkillValidRule,
    AgentSkillNameRule,
    AgentSkillDescriptionRule,
    AgentSkillStructureRule,
    AgentSkillEvalsRequiredRule,
    AgentSkillEvalsRule,
)

from .openclaw import (
    OpenclawMetadataRule,
)

from .instruction_files import (
    InstructionFileValidRule,
    InstructionImportsValidRule,
)

from .context_budget import (
    ContextBudgetRule,
)

from .content_rules import (
    ContentWeakLanguageRule,
    ContentTautologicalRule,
    ContentCriticalPositionRule,
    ContentRedundantWithToolingRule,
    ContentInstructionBudgetRule,
    ContentNegativeOnlyRule,
    ContentSectionLengthRule,
    ContentContradictionRule,
    ContentHookCandidateRule,
    ContentActionabilityScoreRule,
    ContentCognitiveChunksRule,
    ContentEmbeddedSecretsRule,
    ContentBannedReferencesRule,
    ContentInconsistentTerminologyRule,
)

from .coderabbit import (
    CoderabbitYamlValidRule,
)

# All builtin rules
BUILTIN_RULES = [
    # Plugin structure
    PluginJsonRequiredRule,
    PluginJsonValidRule,
    PluginNamingRule,
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
    # Rules directory
    RulesValidRule,
    # Agentskills
    AgentSkillValidRule,
    AgentSkillNameRule,
    AgentSkillDescriptionRule,
    AgentSkillStructureRule,
    AgentSkillEvalsRequiredRule,
    AgentSkillEvalsRule,
    # Openclaw
    OpenclawMetadataRule,
    # Instruction files
    InstructionFileValidRule,
    InstructionImportsValidRule,
    # Context budget
    ContextBudgetRule,
    # Content intelligence
    ContentWeakLanguageRule,
    ContentTautologicalRule,
    ContentCriticalPositionRule,
    ContentRedundantWithToolingRule,
    ContentInstructionBudgetRule,
    ContentNegativeOnlyRule,
    ContentSectionLengthRule,
    ContentContradictionRule,
    ContentHookCandidateRule,
    ContentActionabilityScoreRule,
    ContentCognitiveChunksRule,
    ContentEmbeddedSecretsRule,
    ContentBannedReferencesRule,
    ContentInconsistentTerminologyRule,
    # CodeRabbit
    CoderabbitYamlValidRule,
]


__all__ = [
    "BUILTIN_RULES",
    # Export individual rules too
    "PluginJsonRequiredRule",
    "PluginJsonValidRule",
    "PluginNamingRule",
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
    "RulesValidRule",
    "AgentSkillValidRule",
    "AgentSkillNameRule",
    "AgentSkillDescriptionRule",
    "AgentSkillStructureRule",
    "AgentSkillEvalsRequiredRule",
    "AgentSkillEvalsRule",
    "OpenclawMetadataRule",
    "InstructionFileValidRule",
    "InstructionImportsValidRule",
    "ContextBudgetRule",
    "ContentWeakLanguageRule",
    "ContentTautologicalRule",
    "ContentCriticalPositionRule",
    "ContentRedundantWithToolingRule",
    "ContentInstructionBudgetRule",
    "ContentNegativeOnlyRule",
    "ContentSectionLengthRule",
    "ContentContradictionRule",
    "ContentHookCandidateRule",
    "ContentActionabilityScoreRule",
    "ContentCognitiveChunksRule",
    "ContentEmbeddedSecretsRule",
    "ContentBannedReferencesRule",
    "ContentInconsistentTerminologyRule",
    "CoderabbitYamlValidRule",
]
