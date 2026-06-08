"""
Builtin linting rules for Claude Code plugins
"""

from .plugins import (
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
    HooksDangerousRule,
    HooksProhibitedRule,
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
    AgentSkillRenameRefsRule,
    AgentSkillDescriptionRule,
    AgentSkillStructureRule,
    AgentSkillEvalsRequiredRule,
    AgentSkillEvalsRule,
)

from .openclaw import (
    OpenclawMetadataRule,
)

from .instructions import (
    InstructionFileValidRule,
    InstructionImportsValidRule,
)

from .context_budget import (
    ContextBudgetRule,
)

from .content import (
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
    ContentBrokenInternalReferenceRule,
    ContentUnlinkedInternalReferenceRule,
    ContentPlaceholderTextRule,
)

from .coderabbit import (
    CoderabbitYamlValidRule,
)

from .promptfoo import (
    PromptfooValidRule,
    PromptfooAssertionsRule,
    PromptfooMetadataRule,
)

from .settings import (
    SettingsDangerousRule,
)

from .apm import (
    ApmYamlValidRule,
    ApmStructureValidRule,
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
    HooksDangerousRule,
    HooksProhibitedRule,
    # MCP
    McpValidJsonRule,
    McpProhibitedRule,
    # Rules directory
    RulesValidRule,
    # Agentskills
    AgentSkillValidRule,
    AgentSkillNameRule,
    AgentSkillRenameRefsRule,
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
    ContentBrokenInternalReferenceRule,
    ContentUnlinkedInternalReferenceRule,
    ContentPlaceholderTextRule,
    # CodeRabbit
    CoderabbitYamlValidRule,
    # Promptfoo eval validation
    PromptfooValidRule,
    PromptfooAssertionsRule,
    PromptfooMetadataRule,
    # Settings
    SettingsDangerousRule,
    # APM (Agent Package Manager)
    ApmYamlValidRule,
    ApmStructureValidRule,
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
    "HooksDangerousRule",
    "HooksProhibitedRule",
    "McpValidJsonRule",
    "McpProhibitedRule",
    "RulesValidRule",
    "AgentSkillValidRule",
    "AgentSkillNameRule",
    "AgentSkillRenameRefsRule",
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
    "ContentBrokenInternalReferenceRule",
    "ContentUnlinkedInternalReferenceRule",
    "ContentPlaceholderTextRule",
    "CoderabbitYamlValidRule",
    "PromptfooValidRule",
    "PromptfooAssertionsRule",
    "PromptfooMetadataRule",
    "SettingsDangerousRule",
    "ApmYamlValidRule",
    "ApmStructureValidRule",
]
