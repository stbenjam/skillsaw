"""
Shared helpers for instruction file rules
"""

import re

INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md", "QWEN.md")

# Shared across rule packages so the ``@path`` import grammar has exactly
# one definition.
IMPORT_RE = re.compile(r"(?<![\w./-])@([^\s`<>'\"(){}\[\],;:]+)")
