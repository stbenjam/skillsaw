"""Foundational content-block types.

:class:`ContentBlock` is the abstract base for every leaf node whose text is
prose for an agent's context window; :class:`FileContentBlock` is the concrete
"whole file is lintable" specialization that the typed content blocks build on.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from skillsaw.markdown_doc import MarkdownDoc

from skillsaw.lint_target import LintTarget
from skillsaw.utils import read_text


@dataclass(eq=False)
class ContentBlock(LintTarget):
    """Abstract base for leaf nodes with lintable text content.

    Content blocks hold prose destined for an agent's context window —
    content-quality rules run on every one of them. Structured config
    files (hooks, MCP, settings JSON) are :class:`JsonConfigBlock`
    instead: still in the lint tree, but never linted as prose.
    """

    category: str = ""
    line_offset: int = 0
    body: Optional[str] = None
    _line_map: Optional[Callable[[int], int]] = field(default=None, repr=False)

    def file_line(self, body_line: int) -> int:
        """Translate a 1-based body line number to a 1-based file line number."""
        if self._line_map is not None:
            return self._line_map(body_line)
        return body_line + self.line_offset

    @abstractmethod
    def read_body(self, *, strip_code_blocks: bool = True) -> Optional[str]: ...

    @abstractmethod
    def write_body(self, new_body: str) -> None: ...

    @property
    def markdown(self) -> "MarkdownDoc":
        """Lazily parsed :class:`MarkdownDoc` for this block's body.

        Re-parses automatically when the underlying body text changes (the
        read caches are invalidated per file after autofixes are applied).
        """
        from skillsaw.markdown_doc import MarkdownDoc

        raw = self.read_body(strip_code_blocks=False) or ""
        cached = self.__dict__.get("_markdown_doc")
        if cached is not None and cached.body == raw:
            return cached
        doc = MarkdownDoc(raw, line_offset=self.line_offset, line_map=self._line_map)
        self.__dict__["_markdown_doc"] = doc
        return doc

    def _stripped_body(self) -> str:
        """Body with verbatim content (fences, indented code blocks, code
        spans, HTML comments) blanked, line count preserved."""
        return self.markdown.prose_text()

    def estimate_tokens(self) -> int:
        body = self.read_body()
        return len(body) // 4 if body else 0

    def tree_label(self) -> str:
        return f"{self.path.name} ({self.category})"

    def __eq__(self, other):
        if not isinstance(other, ContentBlock):
            return NotImplemented
        return type(self) is type(other) and self.resolved_path == other.resolved_path

    def __hash__(self):
        return hash((type(self), self.resolved_path))


@dataclass(eq=False)
class FileContentBlock(ContentBlock):
    """A plain file whose entire content is lintable."""

    def read_body(self, *, strip_code_blocks: bool = True) -> Optional[str]:
        if self.body is not None:
            body = self.body
        else:
            content = read_text(self.path)
            if content is None:
                return None
            body = content
        if strip_code_blocks:
            return self._stripped_body()
        return body

    def write_body(self, new_body: str) -> None:
        self.path.write_text(new_body, encoding="utf-8")


# Backward-compat alias
ContentFile = FileContentBlock
