"""Repository lint-tree block hierarchy.

The typed node classes that make up the repository lint tree —
:class:`ContentBlock` (prose for an agent's context window) and
:class:`JsonConfigBlock` (structured machine config), plus the
:class:`FrontmatteredBlock` container and all of their concrete subclasses.

These types are *core* — the lint-tree builder, the rule base classes, and the
docs extractor all depend on them — so they live here rather than inside any
single rule module.  Split across submodules by family:

* :mod:`~skillsaw.blocks.base` — ``ContentBlock``, ``FileContentBlock``
* :mod:`~skillsaw.blocks.content` — prose file blocks (``InstructionBlock`` …)
* :mod:`~skillsaw.blocks.frontmatter` — ``FrontmatteredBlock`` + subclasses
* :mod:`~skillsaw.blocks.json_config` — ``JsonConfigBlock`` + hooks/MCP/settings
* :mod:`~skillsaw.blocks.coderabbit` — ``CodeRabbitContentBlock``
* :mod:`~skillsaw.blocks.promptfoo` — ``PromptfooPromptBlock``
* :mod:`~skillsaw.blocks.toml_config` — ``TomlMcpConfigBlock`` (project TOML)
* :mod:`~skillsaw.blocks.grok` — ``GrokConfigBlock`` (Grok's project TOML)
* :mod:`~skillsaw.blocks.codex` — ``CodexConfigBlock`` (Codex's project TOML)
* :mod:`~skillsaw.blocks.gather` — ``gather_all_content_blocks`` and friends

Everything is re-exported here so ``from skillsaw.blocks import X`` keeps
working; ``skillsaw.rules.builtin.content_analysis`` in turn re-exports from
this package for backward compatibility.
"""

from .base import ContentBlock, ContentFile, FileContentBlock
from .content import (
    AgentsMdBlock,
    ChatmodeBlock,
    ClaudeMdBlock,
    ClineWorkflowBlock,
    ContextFileBlock,
    CursorPromptHookBlock,
    DevinGlobalRuleBlock,
    ExtraBlock,
    GeminiMdBlock,
    GrokRuleBlock,
    InstructionBlock,
    PromptBlock,
    AgentMemoryBlock,
    AgentMemoryIndexBlock,
    AntigravityRuleBlock,
    QwenMdBlock,
    ReadmeBlock,
    SkillRefBlock,
)
from .frontmatter import (
    AgentBlock,
    BodyContent,
    CommandBlock,
    CopilotAgentBlock,
    CopilotPromptBlock,
    CursorCommandBlock,
    CursorRuleBlock,
    DevinRuleBlock,
    DevinSkillBlock,
    FrontmatterField,
    FrontmatteredBlock,
    GrokAgentBlock,
    GrokCommandBlock,
    OpenCodeAgentBlock,
    OpenCodeCommandBlock,
    ParsedFrontmatterBlock,
    PluginRuleBlock,
    SkillBlock,
    _parse_file_frontmatter,
)
from .json_config import (
    HOOK_COMMAND_FIELDS,
    VSCODE_HOOK_COMMAND_FIELDS,
    HookEventConfig,
    HookHandler,
    AgentPluginMcpBlock,
    AntigravityConfigBlock,
    AntigravityHooksBlock,
    AntigravityMcpBlock,
    ClaudeHooksBlock,
    CodexConfigHooksBlock,
    CodexHooksBlock,
    CodexInlineHooksBlock,
    CodexInlineMcpBlock,
    CopilotAgentMcpBlock,
    CursorHooksBlock,
    CursorMcpBlock,
    GrokHooksBlock,
    GrokInlineHooksBlock,
    GrokInlineMcpBlock,
    GrokMcpBlock,
    GrokPluginHooksBlock,
    HooksBlock,
    MuseHooksBlock,
    JsonConfigBlock,
    McpConfigRole,
    McpBlock,
    McpRegistryNpmPackageBlock,
    McpRegistryServerBlock,
    McpServerConfig,
    OpenCodeConfigBlock,
    OpenCodeMcpBlock,
    SettingsBlock,
    SkillsLockBlock,
    VsCodeMcpBlock,
    _parse_json_file,
    json_token,
    parse_hooks_events,
)
from .coderabbit import (
    CodeRabbitContentBlock,
    _CODERABBIT_FILENAME,
    _extract_instructions,
    _find_nth_key_line,
    _find_nth_list_item_key_line,
    _find_yaml_key_line,
    _find_yaml_key_line_after,
)
from .promptfoo import PromptfooPromptBlock
from .openai import OpenAIMetadataBlock
from .toml_config import TomlMcpConfigBlock
from .codex import CodexConfigBlock
from .grok import GrokConfigBlock
from .gather import (
    gather_all_content_blocks,
    gather_all_content_files,
    gather_all_instruction_files,
    _get_body,
    _get_body_from_cf,
)

__all__ = [
    # base
    "ContentBlock",
    "FileContentBlock",
    "ContentFile",
    # content
    "InstructionBlock",
    "DevinGlobalRuleBlock",
    "ClaudeMdBlock",
    "AgentsMdBlock",
    "GeminiMdBlock",
    "GrokRuleBlock",
    "AgentMemoryBlock",
    "AgentMemoryIndexBlock",
    "AntigravityRuleBlock",
    "QwenMdBlock",
    "ClineWorkflowBlock",
    "SkillRefBlock",
    "PromptBlock",
    "ChatmodeBlock",
    "ContextFileBlock",
    "ExtraBlock",
    "ReadmeBlock",
    # frontmatter
    "FrontmatterField",
    "BodyContent",
    "FrontmatteredBlock",
    "ParsedFrontmatterBlock",
    "CursorRuleBlock",
    "DevinRuleBlock",
    "DevinSkillBlock",
    "CursorCommandBlock",
    "CopilotPromptBlock",
    "CopilotAgentBlock",
    "OpenCodeCommandBlock",
    "OpenCodeAgentBlock",
    "GrokCommandBlock",
    "GrokAgentBlock",
    "CommandBlock",
    "AgentBlock",
    "SkillBlock",
    "PluginRuleBlock",
    "_parse_file_frontmatter",
    # json_config
    "HOOK_COMMAND_FIELDS",
    "VSCODE_HOOK_COMMAND_FIELDS",
    "json_token",
    "HookHandler",
    "HookEventConfig",
    "AgentPluginMcpBlock",
    "AntigravityConfigBlock",
    "AntigravityHooksBlock",
    "AntigravityMcpBlock",
    "CursorHooksBlock",
    "CursorMcpBlock",
    "CursorPromptHookBlock",
    "JsonConfigBlock",
    "ClaudeHooksBlock",
    "CodexConfigHooksBlock",
    "CodexHooksBlock",
    "CodexInlineHooksBlock",
    "CodexInlineMcpBlock",
    "CopilotAgentMcpBlock",
    "HooksBlock",
    "MuseHooksBlock",
    "GrokHooksBlock",
    "GrokInlineHooksBlock",
    "GrokInlineMcpBlock",
    "GrokMcpBlock",
    "GrokPluginHooksBlock",
    "McpServerConfig",
    "McpConfigRole",
    "McpBlock",
    "McpRegistryNpmPackageBlock",
    "McpRegistryServerBlock",
    "VsCodeMcpBlock",
    "OpenCodeConfigBlock",
    "OpenCodeMcpBlock",
    "SettingsBlock",
    "SkillsLockBlock",
    "_parse_json_file",
    "parse_hooks_events",
    # coderabbit
    "CodeRabbitContentBlock",
    "_CODERABBIT_FILENAME",
    "_find_yaml_key_line",
    "_find_yaml_key_line_after",
    "_find_nth_key_line",
    "_find_nth_list_item_key_line",
    "_extract_instructions",
    # promptfoo
    "PromptfooPromptBlock",
    # Codex project config
    "CodexConfigBlock",
    "TomlMcpConfigBlock",
    # Grok project config
    "GrokConfigBlock",
    # OpenAI metadata
    "OpenAIMetadataBlock",
    # gather
    "gather_all_content_blocks",
    "gather_all_content_files",
    "gather_all_instruction_files",
    "_get_body",
    "_get_body_from_cf",
]
