"""Helpers that gather content blocks from a repository / lint tree."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

from .base import ContentBlock, FileContentBlock

if TYPE_CHECKING:
    from skillsaw.context import RepositoryContext


def gather_all_content_blocks(context: RepositoryContext) -> List[ContentBlock]:
    """Gather all content blocks via the lint tree."""
    return context.lint_tree.content_blocks()


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
