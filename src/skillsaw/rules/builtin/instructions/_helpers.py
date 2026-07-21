"""
Shared helpers for instruction file rules
"""

import re

INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md", "GEMINI.md")

_IMPORT_RE = re.compile(r"(?<![\w./-])@([^\s`<>'\"(){}\[\],;:]+)")
