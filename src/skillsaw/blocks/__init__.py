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
    ExtraBlock,
    GeminiMdBlock,
    InstructionBlock,
    PromptBlock,
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
    FrontmatterField,
    FrontmatteredBlock,
    ParsedFrontmatterBlock,
    PluginRuleBlock,
    SkillBlock,
    _parse_file_frontmatter,
)
from .json_config import (
    HookEventConfig,
    HookHandler,
    AgentPluginMcpBlock,
    CodexInlineHooksBlock,
    CodexInlineMcpBlock,
    CursorHooksBlock,
    CursorMcpBlock,
    HooksBlock,
    JsonConfigBlock,
    McpBlock,
    McpServerConfig,
    SettingsBlock,
    VsCodeMcpBlock,
    _parse_json_file,
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
    "ClaudeMdBlock",
    "AgentsMdBlock",
    "GeminiMdBlock",
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
    "CursorCommandBlock",
    "CopilotPromptBlock",
    "CopilotAgentBlock",
    "CommandBlock",
    "AgentBlock",
    "SkillBlock",
    "PluginRuleBlock",
    "_parse_file_frontmatter",
    # json_config
    "HookHandler",
    "HookEventConfig",
    "AgentPluginMcpBlock",
    "CursorHooksBlock",
    "CursorMcpBlock",
    "CursorPromptHookBlock",
    "JsonConfigBlock",
    "CodexInlineHooksBlock",
    "CodexInlineMcpBlock",
    "HooksBlock",
    "McpServerConfig",
    "McpBlock",
    "VsCodeMcpBlock",
    "SettingsBlock",
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
    # OpenAI metadata
    "OpenAIMetadataBlock",
    # gather
    "gather_all_content_blocks",
    "gather_all_content_files",
    "gather_all_instruction_files",
    "_get_body",
    "_get_body_from_cf",
]
