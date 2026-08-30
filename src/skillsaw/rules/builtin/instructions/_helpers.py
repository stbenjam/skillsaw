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
    line_start: bool


def iter_instruction_imports(line: str) -> Iterable[Tuple[str, int, int]]:
    """Yield normalized ``(path, start, end)`` imports from one prose line."""
    for match in IMPORT_RE.finditer(line):
        import_path = match.group(1).rstrip(".!?")
        # markdown-it-commonmark preserves strikethrough markers because
        # strikethrough is an extension. Treat a balanced marker as markup,
        # while leaving a real trailing ``~`` in an unwrapped filename alone.
        for marker in ("~~~", "~~", "~"):
            if line.endswith(marker, 0, match.start()) and import_path.endswith(marker):
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
    import_lines: set[int] = set()
    for segment in markdown.text_segments():
        if "@" not in segment.text:
            continue
        for import_path, start, end in iter_instruction_imports(segment.text):
            col_start = segment.col_start + start if segment.col_start is not None else None
            col_end = segment.col_start + end if segment.col_start is not None else None
            line_start = (
                segment.body_line not in import_lines
                and col_start is not None
                and _is_line_start_import_prefix(markdown.line(segment.body_line), col_start)
            )
            import_lines.add(segment.body_line)
            yield InstructionImport(
                import_path,
                segment.body_line,
                segment.file_line,
                col_start,
                col_end,
                line_start,
            )


def _is_line_start_import_prefix(line: str, end: int) -> bool:
    """Whether source before an AST import contains only wrapper syntax."""
    cursor = 0
    while cursor < end and line[cursor].isspace():
        cursor += 1
    while cursor < end:
        character = line[cursor]
        if character == ">":
            cursor += 1
            while cursor < end and line[cursor].isspace():
                cursor += 1
            continue
        if character in "-+":
            cursor += 1
            if cursor >= end or not line[cursor].isspace():
                return False
            while cursor < end and line[cursor].isspace():
                cursor += 1
            continue
        if character.isdecimal():
            cursor += 1
            while cursor < end and line[cursor].isdecimal():
                cursor += 1
            if cursor + 1 < end and line[cursor] in ".)" and line[cursor + 1].isspace():
                cursor += 1
                while cursor < end and line[cursor].isspace():
                    cursor += 1
                continue
            return False
        if character in "*_~":
            cursor += 1
            while cursor < end and line[cursor] in "*_~":
                cursor += 1
            if cursor < end and line[cursor].isspace():
                if line[cursor - 1] != "*":
                    return False
                while cursor < end and line[cursor].isspace():
                    cursor += 1
            continue
        return False
    return True
