"""Typed prose content blocks.

Plain files whose entire content is lintable instruction text.  Each hardcodes
its ``category`` as a class default; rules discover them via ``find(BlockType)``
and ``category`` is kept for backward compat (context_budget limits key on it).
"""

from __future__ import annotations

from dataclasses import dataclass

from skillsaw.lint_target import LintTarget

from .base import FileContentBlock


@dataclass(eq=False)
class InstructionBlock(FileContentBlock):
    """Generic instruction files: .cursorrules, .windsurfrules, copilot-instructions, etc."""

    category: str = "instruction"


@dataclass(eq=False)
class ClaudeMdBlock(InstructionBlock):
    """CLAUDE.md instruction file."""

    category: str = "claude-md"


@dataclass(eq=False)
class AgentsMdBlock(InstructionBlock):
    """AGENTS.md instruction file."""

    category: str = "agents-md"


@dataclass(eq=False)
class GeminiMdBlock(InstructionBlock):
    """GEMINI.md instruction file."""

    category: str = "gemini-md"


@dataclass(eq=False)
class SkillRefBlock(FileContentBlock):
    """references/*.md in skills."""

    category: str = "skill-ref"


@dataclass(eq=False)
class PromptBlock(FileContentBlock):
    """APM prompt files."""

    category: str = "prompt"


@dataclass(eq=False)
class ChatmodeBlock(FileContentBlock):
    """APM chatmode files."""

    category: str = "chatmode"


@dataclass(eq=False)
class ContextFileBlock(FileContentBlock):
    """APM context files."""

    category: str = "context"


@dataclass(eq=False)
class ExtraBlock(FileContentBlock):
    """Extra content paths from config."""

    category: str = "extra"


@dataclass(eq=False)
class ReadmeBlock(LintTarget):
    """README.md in a plugin (not injected into context)."""

    show_tokens = False

    def tree_label(self) -> str:
        return self.path.name
