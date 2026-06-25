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
    ContextFileBlock,
    ExtraBlock,
    GeminiMdBlock,
    InstructionBlock,
    PromptBlock,
    ReadmeBlock,
    SkillRefBlock,
)
from .frontmatter import (
    AgentBlock,
    BodyContent,
    CommandBlock,
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
    HooksBlock,
    JsonConfigBlock,
    McpBlock,
    McpServerConfig,
    SettingsBlock,
    _parse_json_file,
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
    "CommandBlock",
    "AgentBlock",
    "SkillBlock",
    "PluginRuleBlock",
    "_parse_file_frontmatter",
    # json_config
    "HookHandler",
    "HookEventConfig",
    "JsonConfigBlock",
    "HooksBlock",
    "McpServerConfig",
    "McpBlock",
    "SettingsBlock",
    "_parse_json_file",
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
    # gather
    "gather_all_content_blocks",
    "gather_all_content_files",
    "gather_all_instruction_files",
    "_get_body",
    "_get_body_from_cf",
]
