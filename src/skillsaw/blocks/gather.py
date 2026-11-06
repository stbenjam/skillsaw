"""Helpers that gather content blocks from a repository / lint tree."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

from skillsaw.generated import generator_copy_paths

from .base import ContentBlock, FileContentBlock

if TYPE_CHECKING:
    from skillsaw.context import RepositoryContext


def gather_all_content_blocks(context: RepositoryContext) -> List[ContentBlock]:
    """Gather all content blocks via the lint tree."""
    return context.lint_tree.content_blocks()


def gather_editorial_content_blocks(context: RepositoryContext) -> List[ContentBlock]:
    """Keep distinct prose views for editorial aggregation across files."""
    from .generators import is_generator_source

    copies = generator_copy_paths(context.lint_tree)
    blocks = [
        b
        for b in gather_all_content_blocks(context)
        if b.in_generated_copy is None and b.resolved_path not in copies
    ]
    sources = [b for b in blocks if is_generator_source(b)]
    if not sources:
        return blocks
    source_views = {
        (b.resolved_path, b.file_line(1), b.read_body(strip_code_blocks=False)) for b in sources
    }
    return [
        b
        for b in blocks
        if is_generator_source(b)
        or (b.resolved_path, b.file_line(1), b.read_body(strip_code_blocks=False))
        not in source_views
    ]


gather_all_content_files = gather_all_content_blocks


def gather_all_instruction_files(context: RepositoryContext) -> List[Path]:
    """Thin wrapper for backward compatibility."""
    return [block.path for block in gather_all_content_blocks(context)]


def _get_body(path: Path, *, strip_code_blocks: bool = True) -> Optional[str]:
    """Prefer ``ContentBlock.read_body()`` for new code."""
    return FileContentBlock(path=path, category="file").read_body(
        strip_code_blocks=strip_code_blocks
    )


def _get_body_from_cf(cf: ContentBlock, *, strip_code_blocks: bool = True) -> Optional[str]:
    """Backward-compat wrapper around ``ContentBlock.read_body()``."""
    return cf.read_body(strip_code_blocks=strip_code_blocks)
