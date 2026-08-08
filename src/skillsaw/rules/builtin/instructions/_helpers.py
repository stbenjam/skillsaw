"""
Shared helpers for instruction file rules
"""

import re

INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md", "QWEN.md")

_IMPORT_RE = re.compile(r"(?<![\w./-])@([^\s`<>'\"(){}\[\],;:]+)")
