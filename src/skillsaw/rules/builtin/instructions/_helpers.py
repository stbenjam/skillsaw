"""
Shared helpers for instruction file rules
"""

import re
from typing import Iterable, NamedTuple, Optional, Tuple

from skillsaw.formats.devin import is_instruction_filename as is_devin_instruction_filename
from skillsaw.markdown_doc import MarkdownDoc

INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md", "QWEN.md")


def is_instruction_filename(name: str) -> bool:
    """Whether *name* is a plain instruction file skillsaw validates."""
    return name in INSTRUCTION_FILES or is_devin_instruction_filename(name)


# Shared across rule packages so the ``@path`` import grammar has exactly
# one definition.
IMPORT_RE = re.compile(r"(?<![\w./-])@([^\s`<>'\"(){}\[\],;:]+)")


class InstructionImport(NamedTuple):
    """One prose import and its source location in a Markdown document."""

    path: str
    body_line: int
    file_line: int
    col_start: Optional[int]
    col_end: Optional[int]


def iter_instruction_imports(line: str) -> Iterable[Tuple[str, int, int]]:
    """Yield normalized ``(path, start, end)`` imports from one prose line."""
    for match in IMPORT_RE.finditer(line):
        import_path = match.group(1).rstrip(".!?")
        # markdown-it-commonmark preserves strikethrough markers because
        # strikethrough is an extension. Treat a balanced marker as markup,
        # while leaving a real trailing ``~`` in an unwrapped filename alone.
        prefix = line[: match.start()]
        for marker in ("~~~", "~~", "~"):
            if prefix.endswith(marker) and import_path.endswith(marker):
                import_path = import_path[: -len(marker)].rstrip(".!?")
                break
        if import_path:
            yield import_path, match.start(), match.end()


def iter_markdown_instruction_imports(markdown: MarkdownDoc) -> Iterable[InstructionImport]:
    """Yield imports from Markdown prose, excluding code and comments.

    Text segments expose emphasized text without its Markdown delimiters, so
    paths such as ``**@AGENTS.md**`` keep the same target as an unwrapped
    import. Segment columns translate the match back to the source line.
    """
    for segment in markdown.text_segments():
        if "@" not in segment.text:
            continue
        for import_path, start, end in iter_instruction_imports(segment.text):
            col_start = segment.col_start + start if segment.col_start is not None else None
            col_end = segment.col_start + end if segment.col_start is not None else None
            yield InstructionImport(
                import_path,
                segment.body_line,
                segment.file_line,
                col_start,
                col_end,
            )
