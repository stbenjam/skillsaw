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
    AgentsMdStructureRule,
)

from .agents_md import (
    AgentsMdSizeLimitRule,
    AgentsMdOverrideSemanticsRule,
    AgentsMdHierarchyConsistencyRule,
    AgentsMdDeadFileRefsRule,
    AgentsMdDeadCommandRefsRule,
    AgentsMdWeakLanguageRule,
    AgentsMdNegativeOnlyRule,
    AgentsMdSectionLengthRule,
    AgentsMdStructureDeepRule,
    AgentsMdTautologicalRule,
    AgentsMdCriticalPositionRule,
    AgentsMdHookCandidateRule,
)

from .copilot_instructions import (
    CopilotInstructionsValidRule,
    CopilotDotInstructionsValidRule,
    CopilotInstructionsLengthRule,
    CopilotInstructionsLanguageQualityRule,
    CopilotInstructionsActionabilityRule,
    CopilotInstructionsStaleRefsRule,
    CopilotInstructionsDuplicationRule,
    CopilotInstructionsScopeRule,
    CopilotInstructionsFormatRule,
    CopilotInstructionsConflictRule,
    CopilotInstructionsFrontmatterKeysRule,
    CopilotInstructionsExcludeAgentRule,
)

from .gemini import (
    GeminiImportValidRule,
    GeminiImportCircularRule,
    GeminiImportDepthRule,
    GeminiScopeFalsePositiveRule,
    GeminiHierarchyConsistencyRule,
    GeminiSizeLimitRule,
    GeminiDeadFileRefsRule,
    GeminiWeakLanguageRule,
    GeminiTautologicalRule,
    GeminiCriticalPositionRule,
)

from .context_budget import (
    ContextBudgetRule,
)

from .cursor import (
    CursorMdcValidRule,
    CursorRulesDeprecatedRule,
    CursorMdcFrontmatterRule,
    CursorActivationTypeRule,
    CursorCrlfDetectionRule,
    CursorGlobValidRule,
    CursorEmptyBodyRule,
    CursorDescriptionQualityRule,
    CursorGlobOverlapRule,
    CursorRuleSizeRule,
    CursorFrontmatterTypesRule,
    CursorDuplicateRulesRule,
    CursorAlwaysApplyOveruseRule,
)

from .kiro import (
    KiroSteeringValidRule,
)

from .apm import (
    ApmManifestValidRule,
    ApmTargetValidRule,
    ApmTypeValidRule,
    ApmDependenciesValidRule,
    ApmCompilationValidRule,
    ApmMcpTransportRule,
    ApmLockfileConsistencyRule,
    ApmReadmePresentRule,
    ApmEntryPointRule,
    ApmNameConflictRule,
    ApmFieldTypesRule,
    ApmDeprecatedFieldsRule,
)

from .content_rules import (
    ContentWeakLanguageRule,
    ContentDeadReferencesRule,
    ContentTautologicalRule,
    ContentCriticalPositionRule,
    ContentRedundantWithToolingRule,
    ContentInstructionBudgetRule,
    ContentReadmeOverlapRule,
    ContentNegativeOnlyRule,
    ContentSectionLengthRule,
    ContentContradictionRule,
    ContentHookCandidateRule,
    ContentActionabilityScoreRule,
    ContentCognitiveChunksRule,
    ContentEmbeddedSecretsRule,
    ContentCrossFileConsistencyRule,
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
    # Copilot instructions
    CopilotInstructionsValidRule,
    CopilotDotInstructionsValidRule,
    # Copilot deep rules (auto-enabled when copilot files detected)
    CopilotInstructionsLengthRule,
    CopilotInstructionsLanguageQualityRule,
    CopilotInstructionsActionabilityRule,
    CopilotInstructionsStaleRefsRule,
    CopilotInstructionsDuplicationRule,
    CopilotInstructionsScopeRule,
    CopilotInstructionsFormatRule,
    CopilotInstructionsConflictRule,
    CopilotInstructionsFrontmatterKeysRule,
    CopilotInstructionsExcludeAgentRule,
    AgentsMdStructureRule,
    # Deep AGENTS.md rules
    AgentsMdSizeLimitRule,
    AgentsMdOverrideSemanticsRule,
    AgentsMdHierarchyConsistencyRule,
    AgentsMdDeadFileRefsRule,
    AgentsMdDeadCommandRefsRule,
    AgentsMdWeakLanguageRule,
    AgentsMdNegativeOnlyRule,
    AgentsMdSectionLengthRule,
    AgentsMdStructureDeepRule,
    AgentsMdTautologicalRule,
    AgentsMdCriticalPositionRule,
    AgentsMdHookCandidateRule,
    # Context budget
    ContextBudgetRule,
    # Cursor rules (monolithic, default disabled)
    CursorMdcValidRule,
    CursorRulesDeprecatedRule,
    # Kiro steering
    KiroSteeringValidRule,
    # Cursor deep rules (auto-enabled)
    CursorMdcFrontmatterRule,
    CursorActivationTypeRule,
    CursorCrlfDetectionRule,
    CursorGlobValidRule,
    CursorEmptyBodyRule,
    CursorDescriptionQualityRule,
    CursorGlobOverlapRule,
    CursorRuleSizeRule,
    CursorFrontmatterTypesRule,
    CursorDuplicateRulesRule,
    CursorAlwaysApplyOveruseRule,
    # Gemini
    GeminiImportValidRule,
    GeminiImportCircularRule,
    GeminiImportDepthRule,
    GeminiScopeFalsePositiveRule,
    GeminiHierarchyConsistencyRule,
    GeminiSizeLimitRule,
    GeminiDeadFileRefsRule,
    GeminiWeakLanguageRule,
    GeminiTautologicalRule,
    GeminiCriticalPositionRule,
    # APM
    ApmManifestValidRule,
    ApmTargetValidRule,
    ApmTypeValidRule,
    ApmDependenciesValidRule,
    ApmCompilationValidRule,
    # Content intelligence
    ContentWeakLanguageRule,
    ContentDeadReferencesRule,
    ContentTautologicalRule,
    ContentCriticalPositionRule,
    ContentRedundantWithToolingRule,
    ContentInstructionBudgetRule,
    ContentReadmeOverlapRule,
    ContentNegativeOnlyRule,
    ContentSectionLengthRule,
    ContentContradictionRule,
    ContentHookCandidateRule,
    ContentActionabilityScoreRule,
    ContentCognitiveChunksRule,
    ContentEmbeddedSecretsRule,
    ContentCrossFileConsistencyRule,
    ApmMcpTransportRule,
    ApmLockfileConsistencyRule,
    ApmReadmePresentRule,
    ApmEntryPointRule,
    ApmNameConflictRule,
    ApmFieldTypesRule,
    ApmDeprecatedFieldsRule,
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
    "CopilotInstructionsValidRule",
    "CopilotDotInstructionsValidRule",
    "CopilotInstructionsLengthRule",
    "CopilotInstructionsLanguageQualityRule",
    "CopilotInstructionsActionabilityRule",
    "CopilotInstructionsStaleRefsRule",
    "CopilotInstructionsDuplicationRule",
    "CopilotInstructionsScopeRule",
    "CopilotInstructionsFormatRule",
    "CopilotInstructionsConflictRule",
    "CopilotInstructionsFrontmatterKeysRule",
    "CopilotInstructionsExcludeAgentRule",
    "AgentsMdStructureRule",
    "AgentsMdSizeLimitRule",
    "AgentsMdOverrideSemanticsRule",
    "AgentsMdHierarchyConsistencyRule",
    "AgentsMdDeadFileRefsRule",
    "AgentsMdDeadCommandRefsRule",
    "AgentsMdWeakLanguageRule",
    "AgentsMdNegativeOnlyRule",
    "AgentsMdSectionLengthRule",
    "AgentsMdStructureDeepRule",
    "AgentsMdTautologicalRule",
    "AgentsMdCriticalPositionRule",
    "AgentsMdHookCandidateRule",
    "ContextBudgetRule",
    "CursorMdcValidRule",
    "CursorRulesDeprecatedRule",
    "KiroSteeringValidRule",
    "CursorMdcFrontmatterRule",
    "CursorActivationTypeRule",
    "CursorCrlfDetectionRule",
    "CursorGlobValidRule",
    "CursorEmptyBodyRule",
    "CursorDescriptionQualityRule",
    "CursorGlobOverlapRule",
    "CursorRuleSizeRule",
    "CursorFrontmatterTypesRule",
    "CursorDuplicateRulesRule",
    "CursorAlwaysApplyOveruseRule",
    "ApmManifestValidRule",
    "ApmTargetValidRule",
    "ApmTypeValidRule",
    "ApmDependenciesValidRule",
    "ApmCompilationValidRule",
    "ContentWeakLanguageRule",
    "ContentDeadReferencesRule",
    "ContentTautologicalRule",
    "ContentCriticalPositionRule",
    "ContentRedundantWithToolingRule",
    "ContentInstructionBudgetRule",
    "ContentReadmeOverlapRule",
    "ContentNegativeOnlyRule",
    "ContentSectionLengthRule",
    "ContentContradictionRule",
    "ContentHookCandidateRule",
    "ContentActionabilityScoreRule",
    "ContentCognitiveChunksRule",
    "ContentEmbeddedSecretsRule",
    "ContentCrossFileConsistencyRule",
    "GeminiImportValidRule",
    "GeminiImportCircularRule",
    "GeminiImportDepthRule",
    "GeminiScopeFalsePositiveRule",
    "GeminiHierarchyConsistencyRule",
    "GeminiSizeLimitRule",
    "GeminiDeadFileRefsRule",
    "GeminiWeakLanguageRule",
    "GeminiTautologicalRule",
    "GeminiCriticalPositionRule",
]
