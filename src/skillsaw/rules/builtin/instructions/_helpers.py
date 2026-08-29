"""
Shared helpers for instruction file rules
"""

import re

from skillsaw.formats.devin import is_instruction_filename as is_devin_instruction_filename

INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md", "QWEN.md")


def is_instruction_filename(name: str) -> bool:
    """Whether *name* is a plain instruction file skillsaw validates."""
    return name in INSTRUCTION_FILES or is_devin_instruction_filename(name)


# Shared across rule packages so the ``@path`` import grammar has exactly
# one definition.
IMPORT_RE = re.compile(r"(?<![\w./-])@([^\s`<>'\"(){}\[\],;:]+)")
