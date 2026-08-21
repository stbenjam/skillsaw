"""Typed prose content blocks.

Plain files whose entire content is lintable instruction text.  Each hardcodes
its ``category`` as a class default; rules discover them via ``find(BlockType)``
and ``category`` is kept for backward compat (context_budget limits key on it).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, List, Optional

from skillsaw.lint_target import LintTarget

from .base import ContentBlock, FileContentBlock

if TYPE_CHECKING:
    from pathlib import Path


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
class QwenMdBlock(InstructionBlock):
    """QWEN.md instruction file."""

    category: str = "qwen-md"


@dataclass(eq=False)
class ClineWorkflowBlock(FileContentBlock):
    """.clinerules/workflows/*.md — Cline workflows, invoked on demand.

    Budgeted as a ``command`` rather than an ``instruction``: workflows are
    pulled into context when the user types ``/name``, not on every turn.
    """

    category: str = "command"


@dataclass(eq=False)
class CursorPromptHookBlock(ContentBlock):
    """The ``prompt`` string of a Cursor ``type: "prompt"`` hook.

    A prompt hook spawns no process, so it never reaches the command
    scanners through ``CursorHooksBlock.events``. Cursor still injects this
    text verbatim into the agent's context every time the hook's event
    fires, which makes it shipped instruction prose that happens to live in
    a JSON file — exactly what the injection scanners exist to read.

    A ContentBlock for the prompt alone, rather than for ``hooks.json``:
    the rest of the file is configuration, and the prose/config split says
    configuration is never linted as instruction text. Mirrors
    :class:`~skillsaw.blocks.promptfoo.PromptfooPromptBlock`, which extracts
    prompt strings out of an eval config the same way.
    """

    json_path: str = ""
    #: Read, never rewritten: a fix computed against the extracted prompt
    #: has no honest span in the JSON that holds it (the body is a decoded
    #: string literal, and every body line maps to file-level).
    diagnostic_only: ClassVar[bool] = True
    #: Deliberately outside ``DEFAULT_LIMITS``: ``context-budget`` measures a
    #: whole file, and the file here is JSON config shared by every prompt in
    #: it. Charging one embedded string for the whole document — once per
    #: string — would be wrong twice over. ``promptfoo-prompt`` sits out for
    #: the same reason.
    category: str = "hook-prompt"

    def read_body(self, *, strip_code_blocks: bool = True) -> Optional[str]:
        if strip_code_blocks:
            return self._stripped_body()
        return self.body if self.body is not None else ""

    def link_base_dir(self, repo_root: "Path") -> "Path":
        # Cursor injects this prompt into an agent running in the workspace,
        # not from the ``.cursor/`` directory the JSON file lives in — so a
        # relative link like ``docs/setup.md`` names ``<workspace>/docs`` and
        # must resolve from the directory that owns this ``.cursor/``. At the
        # repository root those are the same; in a monorepo the nearest
        # enclosing package is the workspace.
        return self.path.parent.parent

    def write_body(self, new_body: str) -> None:
        # Writing back would mean re-encoding a JSON string literal in place.
        # No rule calls this today, and refusing beats corrupting a config
        # file if one ever does.
        raise NotImplementedError("Cursor prompt hooks are diagnostic-only")

    def file_line(self, body_line: int) -> int:
        # ``json.load`` discards line numbers, so there is no honest mapping
        # from a line of the prompt to a line of the file. 0 renders as a
        # bare path, which is the file-level reporting JSON rules use.
        return 0

    def fingerprint_identity(self, body_line: Optional[int]) -> Optional[str]:
        """Which prompt, and which line of it — the file cannot say either.

        ``file_line`` is 0 here, so a baseline would otherwise fall back to
        hashing the rule, the path and the message. Two prompts carrying
        different payloads that happen to produce the same message (say the
        same invisible codepoint) would then share a fingerprint, and
        baselining one would suppress the other.
        """
        body = self.body or ""
        lines = body.split("\n")
        line_content = ""
        if body_line is not None and 1 <= body_line <= len(lines):
            line_content = lines[body_line - 1].strip()
        # Length-prefixed so the identity is injective: both components can
        # legitimately contain the NUL separator (they come from decoded
        # JSON strings), and plain concatenation lets two different
        # (path, line) pairs collide — which would let baselining one
        # finding suppress a different one.
        return f"{len(self.json_path)}:{self.json_path}\0{line_content}"

    def tree_label(self) -> str:
        return f"{self.json_path} ({self.category})"

    def __eq__(self, other):
        if not isinstance(other, CursorPromptHookBlock):
            return NotImplemented
        return self.resolved_path == other.resolved_path and self.json_path == other.json_path

    def __hash__(self):
        return hash((type(self), self.resolved_path, self.json_path))

    @classmethod
    def gather_from_tree(cls, root: LintTarget) -> List["CursorPromptHookBlock"]:
        """Build one block per prompt hook found under *root*."""
        from .json_config import CursorHooksBlock

        blocks: List[CursorPromptHookBlock] = []
        for node in root.find(CursorHooksBlock):
            if node.parse_error:
                continue
            for event_type, index, prompt in node.prompt_hooks():
                blocks.append(
                    cls(
                        path=node.path,
                        body=prompt,
                        json_path=f"hooks.{event_type}[{index}].prompt",
                    )
                )
        return blocks


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
